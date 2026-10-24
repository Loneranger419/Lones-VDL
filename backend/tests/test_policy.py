"""Download policy end to end: anonymous first, escalation, approval, pause, caps, pacing."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from conftest import (
    MEMBER_COOKIES,
    account_health,
    add_account,
    calls,
    enqueue,
    services,
    wait_for_job,
    wait_until,
)
from sqlalchemy import select

from lones_vdl.db import utcnow
from lones_vdl.db.models import AccessAttempt, AttemptKind
from lones_vdl.services import policy as policy_service

LOGIN1, LOGIN2 = "loginlogi01", "loginlogi02"  # refused anonymously, fine with cookies
MEMBERS = "memberonly1"  # members-only unless the cookies hold MEMBERSHIP


def job(client, job_id: int) -> dict:
    return client.get(f"/api/jobs/{job_id}").json()


def attempts(client, kind: str = AttemptKind.VIDEO) -> list[AccessAttempt]:
    """Recorded request cycles. Video ones by default: a first download also queues a small
    channel-details listing, which has its own attempts."""
    with services(client).sessions() as db:
        query = select(AccessAttempt).where(AccessAttempt.kind == kind).order_by(AccessAttempt.id)
        return list(db.scalars(query))


def policy_status(client) -> dict:
    svc = services(client)
    with svc.sessions() as db:
        return svc.policy.status(db)


def set_runtime(client, **changes) -> None:
    services(client).runtime.update(changes)
    services(client).worker.wake()


# --- anonymous first, then the alternate account ----------------------------------------


def test_anonymous_is_tried_first_and_the_account_stays_unused(authed, fake_state):
    add_account(authed)
    done = wait_for_job(authed, enqueue(authed, "okokokokok1")["id"])
    assert done["status"] == "completed" and done["auth_tier"] == 0
    assert calls(fake_state) == ["okokokokok1 anon"]
    [attempt] = attempts(authed)
    assert attempt.account_pk is None and attempt.outcome == "ok"


def test_refused_anonymous_escalates_to_the_alternate_account(authed, fake_state):
    account_id = add_account(authed)
    done = wait_for_job(authed, enqueue(authed, LOGIN1)["id"])
    assert done["status"] == "completed", done
    assert calls(fake_state) == [f"{LOGIN1} anon", f"{LOGIN1} auth"]
    assert done["auth_tier"] == 1 and done["attempts"] == 1  # escalation is not a retry

    anonymous, signed_in = attempts(authed)
    assert (anonymous.account_pk, anonymous.outcome) == (None, "cookies_missing")
    assert (signed_in.account_pk, signed_in.outcome) == (account_id, "ok")
    assert account_health(authed, account_id) == "ok"


def test_without_an_alternate_account_the_refusal_is_final(authed, fake_state):
    done = wait_for_job(authed, enqueue(authed, LOGIN1)["id"])
    assert (done["status"], done["error_kind"]) == ("failed", "cookies_missing")
    assert calls(fake_state) == [f"{LOGIN1} anon"]


def test_unavailable_video_is_not_escalated(authed, fake_state):
    add_account(authed)
    done = wait_for_job(authed, enqueue(authed, "gonegone001")["id"])
    assert (done["status"], done["error_kind"]) == ("failed", "unavailable")
    assert calls(fake_state) == ["gonegone001 anon"]


# --- members-only: the personal account, only with approval ------------------------------


def test_members_only_waits_for_approval_then_uses_the_personal_account(authed, fake_state):
    add_account(authed)
    personal_id = add_account(authed, "Me", "personal", MEMBER_COOKIES)
    held = enqueue(authed, MEMBERS)
    wait_for_job(authed, held["id"], statuses=("awaiting_approval",))

    waiting = job(authed, held["id"])
    assert waiting["auth_tier"] == 2 and waiting["attempts"] == 0
    assert "Approve" in waiting["error_message"]
    # The alternate account is skipped: the error already says a membership is needed.
    assert calls(fake_state) == [f"{MEMBERS} anon"]

    # Other work is not blocked by a job waiting for a decision, and nothing escalates alone.
    assert wait_for_job(authed, enqueue(authed, "okokokokok1")["id"])["status"] == "completed"
    time.sleep(0.4)
    assert job(authed, held["id"])["status"] == "awaiting_approval"
    assert calls(fake_state) == [f"{MEMBERS} anon", "okokokokok1 anon"]

    assert authed.post(f"/api/jobs/{held['id']}/approve").status_code == 200
    done = wait_for_job(authed, held["id"])
    assert done["status"] == "completed", done
    assert done["approved_at"] is not None
    assert calls(fake_state)[-1] == f"{MEMBERS} auth"
    assert attempts(authed)[-1].account_pk == personal_id


def test_members_only_without_a_personal_account_just_fails(authed):
    add_account(authed)
    done = wait_for_job(authed, enqueue(authed, MEMBERS)["id"])
    assert (done["status"], done["error_kind"]) == ("failed", "members_only")


def test_approving_the_wrong_state_is_rejected_and_waiting_jobs_can_be_cancelled(authed):
    add_account(authed)
    add_account(authed, "Me", "personal", MEMBER_COOKIES)
    done = wait_for_job(authed, enqueue(authed, "okokokokok1")["id"])
    assert authed.post(f"/api/jobs/{done['id']}/approve").status_code == 409

    held = enqueue(authed, MEMBERS)
    wait_for_job(authed, held["id"], statuses=("awaiting_approval",))
    assert authed.post(f"/api/jobs/{held['id']}/cancel").json()["status"] == "cancelled"
    assert authed.post(f"/api/jobs/{held['id']}/approve").status_code == 409


def test_listings_never_use_the_personal_account(authed, fake_state):
    add_account(authed, "Me", "personal", MEMBER_COOKIES)
    listing = authed.post("/api/jobs", json={"url": "https://www.youtube.com/@botchannel"}).json()
    done = wait_for_job(authed, listing["id"])
    assert (done["status"], done["error_kind"]) == ("failed", "cookies_missing")
    seen = (fake_state / "listings").read_text().splitlines()
    assert seen and all(line.endswith(" anon") for line in seen)


# --- rate limits: pause, never rotate -----------------------------------------------------


def test_rate_limit_pauses_all_work_without_switching_accounts(authed, fake_state, monkeypatch):
    monkeypatch.setattr(policy_service, "BACKOFF_SECONDS", (3600.0,))
    svc = services(authed)
    add_account(authed)
    limited = enqueue(authed, "limited0001")
    wait_until(
        lambda: job(authed, limited["id"])["error_kind"] == "rate_limited",
        message="the rate limit to be seen",
    )
    held = job(authed, limited["id"])
    assert held["status"] == "queued" and held["attempts"] == 0  # not charged
    with svc.sessions() as db:
        pause = policy_service.get_pause(db)
    assert pause.active and pause.strikes == 1
    assert policy_status(authed)["paused_until"] is not None

    # Everything waits, and the alternate account is never tried to get around the limit.
    other = enqueue(authed, "okokokokok1")
    time.sleep(0.6)
    assert job(authed, other["id"])["status"] == "queued"
    assert calls(fake_state) == ["limited0001 anon"]

    with svc.sessions.begin() as db:
        policy_service.clear_pause(db)
    svc.worker.wake()
    assert wait_for_job(authed, other["id"])["status"] == "completed"


def test_backoff_grows_with_repeated_rate_limits(authed, monkeypatch):
    monkeypatch.setattr(policy_service, "BACKOFF_SECONDS", (60.0, 120.0, 300.0))
    svc = services(authed)
    waits = []
    with svc.sessions.begin() as db:
        for _ in range(5):
            until = policy_service.register_rate_limit(db, "test")
            waits.append(round((until - utcnow()).total_seconds() / 10))
    assert waits == [6, 12, 30, 30, 30]  # the last step repeats


# --- daily caps -----------------------------------------------------------------------------


def test_daily_cap_counts_only_videos_that_start_downloading(authed):
    set_runtime(authed, daily_download_cap=2)
    gone = enqueue(authed, "gonegone001")  # fails while resolving: does not count
    ids = [enqueue(authed, f"okokokokok{n}")["id"] for n in (1, 2, 3)]
    wait_for_job(authed, gone["id"])
    for job_id in ids[:2]:
        assert wait_for_job(authed, job_id)["status"] == "completed"
    time.sleep(0.5)
    assert job(authed, ids[2])["status"] == "queued"  # waits for the window, no intervention
    status = policy_status(authed)
    assert status["downloads_24h"] == 2 and status["daily_download_cap"] == 2

    set_runtime(authed, daily_download_cap=3)
    assert wait_for_job(authed, ids[2])["status"] == "completed"


def test_a_download_that_fails_midway_still_counts(authed):
    set_runtime(authed, daily_download_cap=1)
    broken = enqueue(authed, "dlfmt000001")
    assert wait_for_job(authed, broken["id"])["error_kind"] == "format_unavailable"
    later = enqueue(authed, "okokokokok1")
    time.sleep(0.5)
    assert job(authed, later["id"])["status"] == "queued"
    assert policy_status(authed)["downloads_24h"] == 1


def test_authenticated_cap_holds_back_only_jobs_that_need_an_account(authed):
    set_runtime(authed, daily_auth_cap=1)
    add_account(authed)
    first = enqueue(authed, LOGIN1)
    second = enqueue(authed, LOGIN2)
    plain = enqueue(authed, "okokokokok1")
    assert wait_for_job(authed, first["id"])["status"] == "completed"
    assert wait_for_job(authed, plain["id"])["status"] == "completed"
    wait_until(lambda: job(authed, second["id"])["auth_tier"] == 1, message="escalation")
    time.sleep(0.5)
    assert job(authed, second["id"])["status"] == "queued"
    assert policy_status(authed)["authenticated_24h"] == 1

    set_runtime(authed, daily_auth_cap=2)
    assert wait_for_job(authed, second["id"])["status"] == "completed"


def test_cap_math():
    now = utcnow()
    starts = [now - timedelta(hours=h) for h in (20, 10, 1)]  # oldest first
    window = policy_service.WINDOW
    assert policy_service._cap_ready(starts, 4, now) == now
    assert policy_service._cap_ready(starts, 3, now) == starts[0] + window
    assert policy_service._cap_ready(starts, 2, now) == starts[1] + window
    assert policy_service._cap_ready([], 1, now) == now


def test_interrupted_attempts_still_count(authed):
    svc = services(authed)
    set_runtime(authed, daily_download_cap=1)
    with svc.sessions.begin() as db:
        db.add(
            AccessAttempt(kind=AttemptKind.VIDEO, started_at=utcnow(), download_started_at=utcnow())
        )
        assert policy_service.mark_interrupted(db) == 1
    [row] = attempts(authed)
    assert row.outcome == "interrupted" and row.finished_at is not None
    later = enqueue(authed, "okokokokok1")
    time.sleep(0.5)
    assert job(authed, later["id"])["status"] == "queued"


# --- pacing ---------------------------------------------------------------------------------


def test_pause_between_videos(authed):
    set_runtime(authed, video_delay_min_seconds=1.5, video_delay_max_seconds=1.5)
    first = enqueue(authed, "okokokokok1")
    second = enqueue(authed, "okokokokok2")
    one = wait_for_job(authed, first["id"])
    two = wait_for_job(authed, second["id"])
    gap = datetime.fromisoformat(two["started_at"]) - datetime.fromisoformat(one["finished_at"])
    assert gap.total_seconds() >= 1.3


def test_gap_between_authenticated_attempts(authed, monkeypatch):
    monkeypatch.setattr(policy_service, "AUTH_GAP_SECONDS", 1.2)
    add_account(authed)
    first = enqueue(authed, LOGIN1)
    second = enqueue(authed, LOGIN2)
    wait_for_job(authed, first["id"])
    wait_for_job(authed, second["id"])
    signed_in = [a for a in attempts(authed) if a.account_pk is not None]
    assert len(signed_in) == 2
    assert (signed_in[1].started_at - signed_in[0].finished_at).total_seconds() >= 1.0


def test_delay_settings_are_limited_to_15_to_30_seconds(authed, monkeypatch):
    monkeypatch.setattr(policy_service, "DELAY_FLOOR", 15.0)
    ok = authed.patch(
        "/api/settings", json={"video_delay_min_seconds": 20, "video_delay_max_seconds": 25}
    )
    assert ok.status_code == 200, ok.text
    for low, high in ((5, 20), (20, 40), (25, 20)):
        bad = authed.patch(
            "/api/settings", json={"video_delay_min_seconds": low, "video_delay_max_seconds": high}
        )
        assert bad.status_code == 422, (low, high)
    assert authed.patch("/api/settings", json={"daily_download_cap": 0}).status_code == 422
