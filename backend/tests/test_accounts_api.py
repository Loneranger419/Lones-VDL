"""Accounts API, policy status, and retrying a job with a chosen account."""

from __future__ import annotations

from conftest import (
    COOKIES,
    MEMBER_COOKIES,
    add_account,
    calls,
    enqueue,
    services,
    wait_for_job,
)
from sqlalchemy import select

from lones_vdl.db.models import AccessAttempt, AttemptKind

PRIVATE = "privatevid1"  # private unless the request is signed in


def make(client, label="Alternate", role="alternate") -> dict:
    response = client.post("/api/accounts", json={"label": label, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, account_id: int, text: str = COOKIES):
    return client.post(
        f"/api/accounts/{account_id}/cookies", content=text, headers={"content-type": "text/plain"}
    )


# --- accounts ---------------------------------------------------------------------------------


def test_create_list_rename_disable_delete(authed):
    assert authed.get("/api/accounts").json() == []
    alt = make(authed)
    assert alt["role"] == "alternate" and alt["enabled"] is True
    assert alt["status"]["present"] is False

    assert (
        authed.post("/api/accounts", json={"label": "Alternate", "role": "personal"}).status_code
        == 409
    )
    assert authed.post("/api/accounts", json={"label": "x", "role": "admin"}).status_code == 422
    assert authed.post("/api/accounts", json={"label": "", "role": "personal"}).status_code == 422

    me = make(authed, "Me", "personal")
    assert [a["label"] for a in authed.get("/api/accounts").json()] == ["Alternate", "Me"]

    renamed = authed.patch(f"/api/accounts/{me['id']}", json={"label": "Main", "enabled": False})
    assert renamed.status_code == 200 and renamed.json()["label"] == "Main"
    assert renamed.json()["enabled"] is False
    assert authed.patch(f"/api/accounts/{me['id']}", json={"label": "Alternate"}).status_code == 409
    assert authed.patch("/api/accounts/999", json={"enabled": True}).status_code == 404

    assert authed.delete(f"/api/accounts/{me['id']}").status_code == 204
    assert [a["label"] for a in authed.get("/api/accounts").json()] == ["Alternate"]
    assert authed.delete(f"/api/accounts/{me['id']}").status_code == 404


def test_accounts_require_a_session_and_the_csrf_header(client):
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/policy").status_code == 401


def test_import_status_and_delete_never_expose_values(authed, settings):
    alt = make(authed)
    imported = upload(authed, alt["id"])
    assert imported.status_code == 200, imported.text
    assert "secret" not in imported.text and "paypal" not in imported.text
    body = imported.json()
    assert body["summary"]["kept"] == 1 and body["summary"]["dropped_domain"] == 1
    assert body["account"]["status"]["login_cookies"] == {"SID": "2100-01-01"}
    assert body["account"]["status"]["health"]["status"] == "untested"
    assert (settings.accounts_dir / f"{alt['id']}.txt").is_file()

    listed = authed.get("/api/accounts")
    assert "secret" not in listed.text and listed.json()[0]["status"]["cookie_count"] == 1

    assert upload(authed, alt["id"], "not cookies").status_code == 422
    assert upload(authed, alt["id"], "x" * (1024 * 1024 + 1)).status_code == 413
    assert upload(authed, 999).status_code == 404

    assert authed.delete(f"/api/accounts/{alt['id']}/cookies").status_code == 204
    after = authed.get("/api/accounts").json()[0]["status"]
    assert after["present"] is False and after["health"]["status"] == "missing"


def test_deleting_an_account_removes_its_cookie_file(authed, settings):
    alt = make(authed)
    upload(authed, alt["id"])
    path = settings.accounts_dir / f"{alt['id']}.txt"
    assert path.is_file()
    authed.delete(f"/api/accounts/{alt['id']}")
    assert not path.exists()


def test_account_test_records_health_and_an_attempt(authed, settings):
    alt = make(authed)
    upload(authed, alt["id"])
    assert authed.post(f"/api/accounts/{alt['id']}/test").json()["status"] == "ok"

    settings.cookie_test_url = "https://youtu.be/rotrotrot01"
    assert authed.post(f"/api/accounts/{alt['id']}/test").json()["status"] == "invalid"
    health = authed.get("/api/accounts").json()[0]["status"]["health"]
    assert health["status"] == "invalid"

    with services(authed).sessions() as db:
        kinds = list(db.scalars(select(AccessAttempt.kind)))
    assert kinds == [AttemptKind.TEST, AttemptKind.TEST]
    assert authed.post("/api/accounts/999/test").status_code == 404


def test_importing_requeues_jobs_that_failed_for_lack_of_cookies(authed):
    alt = make(authed)
    failed = wait_for_job(authed, enqueue(authed, "loginlogi01")["id"])
    assert failed["error_kind"] == "cookies_missing"
    other = wait_for_job(authed, enqueue(authed, "gonegone001")["id"])

    imported = upload(authed, alt["id"]).json()
    assert imported["requeued_jobs"] == 1
    assert wait_for_job(authed, failed["id"])["status"] == "completed"
    assert authed.get(f"/api/jobs/{other['id']}").json()["status"] == "failed"


def test_importing_a_personal_account_rescues_members_only_failures(authed):
    add_account(authed)  # alternate
    failed = wait_for_job(authed, enqueue(authed, "memberonly1")["id"])
    assert failed["error_kind"] == "members_only"  # no personal account yet

    me = make(authed, "Me", "personal")
    assert upload(authed, me["id"], MEMBER_COOKIES).json()["requeued_jobs"] == 1
    held = wait_for_job(authed, failed["id"], statuses=("awaiting_approval",))
    assert held["auth_tier"] == 2  # still needs the user's approval


# --- policy status ------------------------------------------------------------------------------


def test_policy_status_reports_use_and_anonymous_results(authed):
    empty = authed.get("/api/policy").json()
    assert empty["downloads_24h"] == 0 and empty["daily_download_cap"] == 50
    assert empty["daily_auth_cap"] == 10 and empty["paused_until"] is None

    add_account(authed)
    wait_for_job(authed, enqueue(authed, "okokokokok1")["id"])
    wait_for_job(authed, enqueue(authed, "loginlogi01")["id"])
    wait_for_job(authed, enqueue(authed, "gonegone001")["id"])

    status = authed.get("/api/policy").json()
    assert status["downloads_24h"] == 2 and status["authenticated_24h"] == 1
    assert status["anonymous_ok_7d"] == 1
    assert status["anonymous_refused_7d"] == 1
    assert status["anonymous_other_7d"] == 1  # the unavailable video


# --- retry with an account ------------------------------------------------------------------------


def test_private_video_fails_then_can_be_retried_with_an_account(authed, fake_state):
    alt = add_account(authed)
    failed = wait_for_job(authed, enqueue(authed, PRIVATE)["id"])
    assert (failed["status"], failed["error_kind"]) == ("failed", "unavailable")
    assert calls(fake_state) == [f"{PRIVATE} anon"]  # nothing guessed on its own

    retried = authed.post(f"/api/jobs/{failed['id']}/retry", json={"account_id": alt})
    assert retried.status_code == 200, retried.text
    assert retried.json()["auth_tier"] == 1 and retried.json()["options"] == {"account_id": alt}
    done = wait_for_job(authed, failed["id"])
    assert done["status"] == "completed", done
    assert calls(fake_state)[-1] == f"{PRIVATE} auth"


def test_retry_with_the_personal_account_counts_as_approval(authed, fake_state):
    add_account(authed)
    personal = add_account(authed, "Me", "personal")
    failed = wait_for_job(authed, enqueue(authed, PRIVATE)["id"])
    retried = authed.post(f"/api/jobs/{failed['id']}/retry", json={"account_id": personal})
    assert retried.json()["auth_tier"] == 2 and retried.json()["approved_at"] is not None
    assert wait_for_job(authed, failed["id"])["status"] == "completed"


def test_retry_with_a_chosen_account_is_validated(authed):
    alt = add_account(authed)
    personal = add_account(authed, "Me", "personal")
    failed = wait_for_job(authed, enqueue(authed, "gonegone001")["id"])
    assert (
        authed.post(f"/api/jobs/{failed['id']}/retry", json={"account_id": 999}).status_code == 404
    )

    authed.patch(f"/api/accounts/{alt}", json={"enabled": False})
    assert (
        authed.post(f"/api/jobs/{failed['id']}/retry", json={"account_id": alt}).status_code == 409
    )

    listing = authed.post("/api/jobs", json={"url": "https://www.youtube.com/@botchannel"}).json()
    wait_for_job(authed, listing["id"])
    refused = authed.post(f"/api/jobs/{listing['id']}/retry", json={"account_id": personal})
    assert refused.status_code == 409 and "personal" in refused.json()["detail"]


def test_a_plain_retry_starts_over_anonymous(authed, fake_state):
    add_account(authed)
    failed = wait_for_job(authed, enqueue(authed, "botbotbot01")["id"])
    assert failed["auth_tier"] == 1 and failed["error_kind"] == "auth_required"

    retried = authed.post(f"/api/jobs/{failed['id']}/retry").json()
    assert retried["auth_tier"] == 0 and retried["options"] is None
    wait_for_job(authed, failed["id"])
    assert calls(fake_state)[2:] == ["botbotbot01 anon", "botbotbot01 auth"]
