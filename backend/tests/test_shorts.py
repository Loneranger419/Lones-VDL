"""Shorts: their own daily caps, and they give way to videos and streams."""

from __future__ import annotations

from datetime import timedelta

from conftest import (
    add_account,
    enqueue,
    services,
    set_listings,
    wait_for_job,
    wait_idle,
    wait_until,
    youtube_limits,
)

from lones_vdl.db import utcnow
from lones_vdl.db.models import AccessAttempt, Job, JobStatus
from lones_vdl.services import policy as policy_service

SHORT_A, SHORT_B = "shortshort1", "shortshort2"  # ids containing "short" are portrait and brief
VIDEO_A, VIDEO_B = "okokokokok1", "okokokokok2"
LOGIN_SHORT = "loginshort1"  # a short that YouTube refuses anonymously
CHANNEL_URL = "https://www.youtube.com/@fakechannel"


def set_runtime(client, **changes) -> None:
    services(client).runtime.update(changes)
    services(client).worker.wake()


def short(client, video_id: str) -> dict:
    """Queue a short by its /shorts/ link, so it is known to be one before it is resolved."""
    response = client.post("/api/jobs", json={"url": f"https://www.youtube.com/shorts/{video_id}"})
    assert response.status_code == 201, response.text
    return response.json()


def limits(client) -> dict:
    return youtube_limits(client.get("/api/policy").json())


def job(client, job_id: int) -> dict:
    return client.get(f"/api/jobs/{job_id}").json()


def hold_everything(client, seconds: float = 1.5) -> None:
    """Pause YouTube work briefly, so jobs queued meanwhile all become ready at the same moment."""
    with services(client).sessions.begin() as db:
        until = utcnow() + timedelta(seconds=seconds)
        policy_service._put_pause(db, policy_service.Pause(until, "test", 1))


# --- what counts as a short ------------------------------------------------------------------


def test_shorts_url_and_shorts_tab_are_recognised(authed, fake_state):
    assert short(authed, SHORT_A)["content_kind"] == "short"
    assert enqueue(authed, VIDEO_A)["content_kind"] is None

    set_listings(fake_state, {"videos": [VIDEO_B], "shorts": ["shortshort3"]})
    parent = authed.post(
        "/api/jobs", json={"url": CHANNEL_URL, "tabs": ["videos", "shorts"]}
    ).json()
    wait_for_job(authed, parent["id"])
    kinds = {
        c["video_id"]: c["content_kind"]
        for c in authed.get("/api/jobs", params={"parent": parent["id"]}).json()
    }
    assert kinds == {VIDEO_B: None, "shortshort3": "short"}
    wait_idle(authed)


# --- their own caps --------------------------------------------------------------------------


def test_shorts_have_their_own_caps(authed):
    set_runtime(authed, shorts_daily_cap=1)
    first = wait_for_job(authed, short(authed, SHORT_A)["id"])
    assert first["status"] == "completed" and first["content_kind"] == "short"
    held = short(authed, SHORT_B)
    assert limits(authed)["shorts"]["used"] == 1
    assert limits(authed)["downloads_24h"] == 0  # videos were not touched

    # A video still runs while the shorts are used up, and the second short keeps waiting.
    video = wait_for_job(authed, enqueue(authed, VIDEO_A)["id"])
    assert video["status"] == "completed"
    assert job(authed, held["id"])["status"] == "queued"
    assert limits(authed)["downloads_24h"] == 1

    set_runtime(authed, shorts_daily_cap=2)
    assert wait_for_job(authed, held["id"])["status"] == "completed"
    assert limits(authed)["shorts"]["used"] == 2


def test_video_cap_does_not_count_shorts(authed):
    set_runtime(authed, daily_download_cap=1)
    wait_for_job(authed, enqueue(authed, VIDEO_A)["id"])
    # The video cap is full. The shorts pool is separate, so a short still runs.
    assert wait_for_job(authed, short(authed, SHORT_A)["id"])["status"] == "completed"
    assert limits(authed)["shorts"]["used"] == 1


def test_shorts_have_their_own_account_cap(authed):
    add_account(authed)
    set_runtime(authed, shorts_daily_auth_cap=0)
    held = short(authed, LOGIN_SHORT)
    # Anonymous is refused, the alternate account is next, but no short may use an account.
    wait_until(
        lambda: (j := job(authed, held["id"]))["auth_tier"] == 1 and j["status"] == "queued",
        message="escalation to the account",
    )

    set_runtime(authed, shorts_daily_auth_cap=1)
    assert wait_for_job(authed, held["id"])["status"] == "completed"
    shorts = limits(authed)["shorts"]
    assert (shorts["used"], shorts["auth_used"]) == (1, 1)
    assert limits(authed)["authenticated_24h"] == 0  # the video account cap is untouched


# --- shorts wait for videos ------------------------------------------------------------------


def test_videos_run_before_shorts_that_were_queued_first(authed):
    hold_everything(authed)
    queued_short = short(authed, SHORT_A)
    video = enqueue(authed, VIDEO_A)

    video_done = wait_for_job(authed, video["id"])
    short_done = wait_for_job(authed, queued_short["id"])
    assert video_done["status"] == short_done["status"] == "completed"
    assert video_done["finished_at"] <= short_done["started_at"]


def test_a_video_held_by_its_own_cap_does_not_hold_shorts_back(authed):
    set_runtime(authed, daily_download_cap=1)
    wait_for_job(authed, enqueue(authed, VIDEO_A)["id"])
    stuck = enqueue(authed, VIDEO_B)  # waits for tomorrow
    done = wait_for_job(authed, short(authed, SHORT_A)["id"])
    assert done["status"] == "completed"
    assert job(authed, stuck["id"])["status"] == "queued"


def test_a_long_run_of_held_videos_does_not_hide_a_short(authed, monkeypatch):
    from lones_vdl.services import jobs as job_service

    monkeypatch.setattr(job_service, "CANDIDATE_LIMIT", 2)
    set_runtime(authed, daily_download_cap=1)
    wait_for_job(authed, enqueue(authed, VIDEO_A)["id"])
    for video_id in ("okokokokok3", "okokokokok4", "okokokokok5", VIDEO_B):
        enqueue(authed, video_id)  # all held by the cap, and ahead of the short in the queue
    done = wait_for_job(authed, short(authed, SHORT_A)["id"])
    assert done["status"] == "completed"


def test_a_job_approved_by_hand_ignores_the_daily_video_cap(authed):
    set_runtime(authed, daily_download_cap=1)
    wait_for_job(authed, enqueue(authed, VIDEO_A)["id"])
    held = enqueue(authed, VIDEO_B)
    assert job(authed, held["id"])["status"] == "queued"
    with services(authed).sessions.begin() as db:
        db.get(Job, held["id"]).approved_at = utcnow()
    services(authed).worker.wake()
    assert wait_for_job(authed, held["id"])["status"] == "completed"
    assert limits(authed)["downloads_24h"] == 2  # it still counts


def test_a_short_only_recognised_after_resolving_steps_aside(authed):
    hold_everything(authed)
    # Looks like any video until it is resolved, so it is claimed first.
    late = enqueue(authed, SHORT_A)
    assert late["content_kind"] is None
    video = enqueue(authed, VIDEO_A)

    video_done = wait_for_job(authed, video["id"])
    late_done = wait_for_job(authed, late["id"])
    assert late_done["status"] == "completed" and late_done["content_kind"] == "short"
    assert late_done["attempts"] == 1  # stepping aside did not cost an attempt
    assert video_done["finished_at"] <= late_done["finished_at"]

    with services(authed).sessions() as db:
        outcomes = [a.outcome for a in db.query(AccessAttempt).order_by(AccessAttempt.id)]
    assert "deferred" in outcomes
    assert limits(authed)["shorts"]["used"] == 1


def test_settings_validate_the_shorts_caps(authed):
    current = authed.get("/api/settings").json()["current"]
    assert (current["shorts_daily_cap"], current["shorts_daily_auth_cap"]) == (100, 5)
    assert authed.patch("/api/settings", json={"shorts_daily_cap": 0}).status_code == 422
    ok = authed.patch("/api/settings", json={"shorts_daily_cap": 30, "shorts_daily_auth_cap": 0})
    assert ok.status_code == 200 and ok.json()["current"]["shorts_daily_cap"] == 30
    assert [g["key"] for g in authed.get("/api/policy").json()["platforms"][0]["groups"]] == [
        "videos",
        "shorts",
    ]


# --- the queue as the Downloads page shows it --------------------------------------------------


def test_queue_summary_counts_waiting_jobs_by_type(authed, fake_state):
    hold_everything(authed, seconds=4)
    enqueue(authed, VIDEO_A)
    enqueue(authed, VIDEO_B)
    short(authed, SHORT_A)
    authed.post("/api/jobs", json={"url": CHANNEL_URL})
    summary = authed.get("/api/jobs/queue").json()
    assert summary == {"videos": 2, "shorts": 1, "streams": 0, "listings": 1, "subtitles": 0}
    wait_idle(authed, timeout=40)
    assert authed.get("/api/jobs/queue").json()["videos"] == 0


def test_queue_order_lists_running_jobs_first(authed):
    hold_everything(authed, seconds=4)
    first = enqueue(authed, VIDEO_A)
    last = enqueue(authed, VIDEO_B)
    params = {"status": ["queued", "running"], "order": "queue"}
    assert [j["id"] for j in authed.get("/api/jobs", params=params).json()] == [
        first["id"],
        last["id"],
    ]
    with services(authed).sessions.begin() as db:  # as if the newest job had just started
        db.get(Job, last["id"]).status = JobStatus.RUNNING
    ids = [j["id"] for j in authed.get("/api/jobs", params=params).json()]
    assert ids == [last["id"], first["id"]]
    with services(authed).sessions.begin() as db:
        db.get(Job, last["id"]).status = JobStatus.QUEUED
    wait_idle(authed, timeout=40)
