"""End to end: API → queue → worker → fake yt-dlp subprocess → archive → index."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from conftest import account_health, add_account, calls, enqueue, wait_for_job


def test_download_archives_and_indexes(authed, settings):
    job = enqueue(authed, "okokokokok1", quality="720")
    assert job["status"] in ("queued", "running")

    done = wait_for_job(authed, job["id"])
    assert done["status"] == "completed", done
    assert done["title"] == "Title okokokokok1"
    assert done["ytdlp_version"] == "2099.01.01"
    assert done["attempts"] == 1

    item = settings.archive_root / "youtube" / "okokokokok1"
    names = sorted(p.relative_to(item).as_posix() for p in item.rglob("*") if p.is_file())
    assert names == [
        "checksums.json",
        "info.json",
        "media.webm",
        "metadata.json",
        "thumbnail.jpg",
    ]
    metadata = json.loads((item / "metadata.json").read_text())
    assert metadata["video_id"] == "okokokokok1"
    assert metadata["content_kind"] == "video"
    assert metadata["files"]["media"] == "media.webm"
    assert metadata["archived_by"]["ytdlp_version"] == "2099.01.01"
    sums = json.loads((item / "checksums.json").read_text())["files"]
    assert sums["media.webm"] == hashlib.sha256((item / "media.webm").read_bytes()).hexdigest()
    assert not any(settings.partial_dir.iterdir())

    page = authed.get("/api/videos").json()
    assert page["total"] == 1
    videos = page["items"]
    assert videos[0]["video_id"] == "okokokokok1"
    assert videos[0]["channel"]["handle"] == "@fakechannel"
    assert videos[0]["watched"] is False and videos[0]["has_thumbnail"] is True
    detail = authed.get(f"/api/videos/{done['video_pk']}").json()
    assert detail["directory"] == "youtube/okokokokok1"
    assert detail["upload_date"] == "2024-01-02"

    log = authed.get(f"/api/jobs/{job['id']}/log").text
    assert "archived to" in log and "fake resolve" in log


def test_duplicates_are_rejected(authed):
    wait_for_job(authed, enqueue(authed, "okokokokok1")["id"])
    again = authed.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=okokokokok1"})
    assert again.status_code == 409
    assert again.json()["kind"] == "conflict"


def test_rejects_unsupported_input(authed):
    for url in ("https://vimeo.com/123", "https://www.youtube.com/feed/history", "not a url"):
        response = authed.post("/api/jobs", json={"url": url})
        assert response.status_code == 422, url
    bad_quality = authed.post(
        "/api/jobs", json={"url": "https://youtu.be/okokokokok1", "quality": "8k"}
    )
    assert bad_quality.status_code == 422


def test_bot_check_without_cookies_is_cookies_missing(authed):
    done = wait_for_job(authed, enqueue(authed, "botbotbot01")["id"])
    assert done["status"] == "failed"
    assert done["error_kind"] == "cookies_missing"
    assert done["attempts"] == 1  # not retryable


def test_bot_check_with_cookies_is_auth_required(authed, fake_state):
    add_account(authed)
    done = wait_for_job(authed, enqueue(authed, "botbotbot01")["id"])
    assert done["status"] == "failed" and done["error_kind"] == "auth_required"
    # Anonymous first, then the alternate account once; escalation is not a retry.
    assert calls(fake_state) == ["botbotbot01 anon", "botbotbot01 auth"]
    assert done["attempts"] == 1 and done["auth_tier"] == 1


def test_rotated_cookies_are_reported(authed):
    account_id = add_account(authed)
    done = wait_for_job(authed, enqueue(authed, "rotrotrot01")["id"])
    assert done["error_kind"] == "cookies_invalid"
    assert "private browser window" in done["error_message"]
    assert account_health(authed, account_id) == "invalid"


def test_unavailable_is_not_retried(authed):
    done = wait_for_job(authed, enqueue(authed, "gonegone001")["id"])
    assert (done["status"], done["error_kind"], done["attempts"]) == ("failed", "unavailable", 1)


def test_rate_limit_is_waited_out_not_charged(authed):
    done = wait_for_job(authed, enqueue(authed, "flakyflaky1")["id"])
    assert done["status"] == "completed"
    assert done["attempts"] == 1  # a rate limit is not the job's fault


def test_downloads_skip_subtitles(authed, settings, fake_state):
    done = wait_for_job(authed, enqueue(authed, "subfail0001")["id"])
    assert done["status"] == "completed", done  # a subtitle error cannot reach the download
    assert not (settings.archive_root / "youtube" / "subfail0001" / "subtitles").exists()


def test_cookie_copy_is_private_and_removed(authed, settings, fake_state):
    account_id = add_account(authed)
    # An anonymous-refused video escalates to the account, which is what makes a copy.
    wait_for_job(authed, enqueue(authed, "loginlogi01")["id"])
    seen = [Path(p) for p in (fake_state / "cookies_seen").read_text().splitlines()]
    assert seen
    for path in seen:
        assert path.is_relative_to(settings.data_dir)  # never on the archive share
        assert not path.exists()
    stored = (settings.accounts_dir / f"{account_id}.txt").read_text()
    assert "paypal" not in stored and "SID" in stored


def test_cancel_running_job(authed, settings):
    job = enqueue(authed, "slowslow001")
    wait_for_job(authed, job["id"], statuses=("running",))
    # wait until the download stage so a real subprocess is attached
    for _ in range(200):
        if authed.get(f"/api/jobs/{job['id']}").json()["stage"] == "downloading":
            break
        __import__("time").sleep(0.05)
    assert authed.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    done = wait_for_job(authed, job["id"])
    assert done["status"] == "cancelled"
    assert not (settings.partial_dir / str(job["id"])).exists()


def test_retry_and_delete_failed_job(authed):
    job = wait_for_job(authed, enqueue(authed, "gonegone001")["id"])
    assert authed.post(f"/api/jobs/{job['id']}/retry").status_code == 200
    job = wait_for_job(authed, job["id"])
    assert job["status"] == "failed"
    assert authed.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert authed.get(f"/api/jobs/{job['id']}").status_code == 404


def test_cannot_delete_active_job(authed):
    job = enqueue(authed, "slowslow001")
    assert authed.delete(f"/api/jobs/{job['id']}").status_code == 409
    authed.post(f"/api/jobs/{job['id']}/cancel")
    wait_for_job(authed, job["id"])
