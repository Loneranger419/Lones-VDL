"""Subtitles are skipped on download and fetched on request as a small job of their own."""

from __future__ import annotations

import hashlib
import json

from conftest import enqueue, wait_for_job, wait_idle


def archived(authed, video_id: str) -> int:
    wait_for_job(authed, enqueue(authed, video_id)["id"])
    page = authed.get("/api/videos", params={"q": video_id}).json()
    return page["items"][0]["id"]


def test_fetch_adds_subtitles_to_the_archive(authed, settings, fake_state):
    pk = archived(authed, "okokokokok1")
    item = settings.archive_root / "youtube" / "okokokokok1"
    media_sum = json.loads((item / "checksums.json").read_text())["files"]["media.webm"]

    response = authed.post(f"/api/videos/{pk}/subtitles")
    assert response.status_code == 202
    done = wait_for_job(authed, response.json()["id"])
    assert done["status"] == "completed", done
    assert done["kind"] == "subtitles"

    assert authed.get(f"/api/videos/{pk}").json()["subtitles"] == ["en"]
    assert authed.get(f"/api/videos/{pk}/subtitles/en.vtt").text.startswith("WEBVTT")
    sums = json.loads((item / "checksums.json").read_text())["files"]
    assert sums["media.webm"] == media_sum  # the media was not touched
    vtt = (item / "subtitles" / "en.vtt").read_bytes()
    assert sums["subtitles/en.vtt"] == hashlib.sha256(vtt).hexdigest()
    assert (
        sums["metadata.json"] == hashlib.sha256((item / "metadata.json").read_bytes()).hexdigest()
    )
    assert json.loads((item / "metadata.json").read_text())["files"]["subtitles"] == [
        "subtitles/en.vtt"
    ]
    verify = authed.post("/api/system/verify")
    assert verify.status_code == 201
    wait_for_job(authed, verify.json()["id"])
    assert authed.get(f"/api/videos/{pk}").json()["integrity"] == "ok"
    assert "okokokokok1 anon" in (fake_state / "subtitle_calls").read_text()
    assert not (settings.data_dir / "tmp" / f"job-{done['id']}").exists()


def test_already_fetched_is_a_conflict(authed):
    pk = archived(authed, "okokokokok1")
    wait_for_job(authed, authed.post(f"/api/videos/{pk}/subtitles").json()["id"])
    again = authed.post(f"/api/videos/{pk}/subtitles")
    assert again.status_code == 409


def test_no_subtitles_is_reported_plainly(authed):
    pk = archived(authed, "nosubs00001")
    done = wait_for_job(authed, authed.post(f"/api/videos/{pk}/subtitles").json()["id"])
    assert done["status"] == "failed"
    assert done["error_kind"] == "no_subtitles"
    assert done["attempts"] == 1  # nothing to retry
    assert authed.get(f"/api/videos/{pk}").json()["subtitles"] == []
    wait_idle(authed)


def test_unknown_video(authed):
    assert authed.post("/api/videos/999/subtitles").status_code == 404
