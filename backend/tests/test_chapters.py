"""Chapters and "most replayed" sections come from the archived info.json."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from conftest import enqueue, services, wait_for_job, wait_idle

from lones_vdl.db import utcnow
from lones_vdl.db.models import Integrity, Video
from lones_vdl.services import chapters as chapter_service
from lones_vdl.services import policy as policy_service
from lones_vdl.services.integrity import verify_dir
from lones_vdl.ytdlp import CancelToken

WITH = "chapvideo01"
WITHOUT = "plainvid001"


def video_id(client, vid: str) -> int:
    return next(v["id"] for v in client.get("/api/videos").json()["items"] if v["video_id"] == vid)


def archive_both(client) -> None:
    enqueue(client, WITH)
    enqueue(client, WITHOUT)
    wait_idle(client)


def test_chapters_and_heatmap_are_served(authed):
    archive_both(authed)
    pk = video_id(authed, WITH)
    data = authed.get(f"/api/videos/{pk}/chapters").json()
    assert [(c["start"], c["end"], c["title"]) for c in data["chapters"]] == [
        (0, 20, "Intro & <setup>"),
        (20, 63, "Main part"),
    ]
    assert [h["value"] for h in data["heatmap"]] == [0.4, 1.0]
    detail = authed.get(f"/api/videos/{pk}").json()
    assert (detail["chapter_count"], detail["has_heatmap"]) == (2, True)


def test_chapters_as_a_webvtt_track(authed):
    archive_both(authed)
    response = authed.get(f"/api/videos/{video_id(authed, WITH)}/chapters.vtt")
    assert response.headers["content-type"].startswith("text/vtt")
    assert response.text == (
        "WEBVTT\n\n"
        "1\n00:00:00.000 --> 00:00:20.000\nIntro &amp; &lt;setup&gt;\n\n"
        "2\n00:00:20.000 --> 00:01:03.000\nMain part\n"
    )


def test_a_video_without_chapters_has_none(authed):
    archive_both(authed)
    pk = video_id(authed, WITHOUT)
    assert authed.get(f"/api/videos/{pk}/chapters").json() == {"chapters": [], "heatmap": []}
    assert authed.get(f"/api/videos/{pk}/chapters.vtt").status_code == 404
    detail = authed.get(f"/api/videos/{pk}").json()
    assert (detail["chapter_count"], detail["has_heatmap"]) == (0, False)


def test_a_changed_info_json_is_picked_up(authed):
    archive_both(authed)
    pk = video_id(authed, WITH)
    assert len(authed.get(f"/api/videos/{pk}/chapters").json()["chapters"]) == 2
    svc = services(authed)
    info = next(svc.settings.archive_root.glob(f"youtube/{WITH}/info.json"))
    data = json.loads(info.read_text(encoding="utf-8"))
    data["chapters"] = data["chapters"][:1]
    info.write_text(
        json.dumps(data) + " ", encoding="utf-8"
    )  # a different size, so a new cache key
    assert len(authed.get(f"/api/videos/{pk}/chapters").json()["chapters"]) == 1


def test_parse_drops_bad_entries_and_fills_gaps():
    info = {
        "chapters": [
            {"start_time": 30, "title": "  Second   part "},  # no end: runs to the next / the end
            {"start_time": 0, "end_time": 30, "title": ""},  # unnamed
            {"start_time": "x", "title": "junk"},
            {"start_time": 500, "end_time": 600, "title": "past the end"},
            "not a dict",
        ],
        "heatmap": [
            {"start_time": 0, "end_time": 10, "value": 3.0},  # clamped
            {"start_time": 10, "end_time": 5, "value": 0.5},  # backwards
            {"start_time": 10, "end_time": 20},  # no value
        ],
    }
    found = chapter_service.parse(info, duration=100)
    assert [(c.start, c.end, c.title) for c in found.chapters] == [
        (0, 30, "Chapter 1"),
        (30, 100, "Second part"),
    ]
    assert [(h.start, h.end, h.value) for h in found.heatmap] == [(0, 10, 1.0)]
    assert chapter_service.parse({"chapters": "oops", "heatmap": 5}, None) == (
        chapter_service.VideoChapters()
    )


# --- looking again for chapters of a recent video -------------------------------------------------

RECENT = "newvideo001"  # published today, no chapters
RECENT_LATE = "newlate0001"  # published today; chapters show up once the test says so
RECENT_CHAPTERED = "newchap0001"
HOUR = timedelta(hours=1)


def detail(client, vid: str) -> dict:
    return client.get(f"/api/videos/{video_id(client, vid)}").json()


def check(client, vid: str):
    response = client.post(f"/api/videos/{video_id(client, vid)}/chapters/check")
    assert response.status_code in (200, 202), response.text
    return response.json()


def set_checked(client, vid: str, when) -> None:
    with services(client).sessions.begin() as db:
        db.get(Video, video_id(client, vid)).chapters_checked_at = when


def test_check_due_rules():
    now = utcnow()
    video = SimpleNamespace(
        platform="youtube",
        upload_date=(now - timedelta(days=3)).date(),
        archived_at=now,
        chapters_checked_at=None,
    )
    assert chapter_service.check_due(video, 0, 0, now)
    assert not chapter_service.check_due(video, 2, 5, now)  # has both
    assert chapter_service.check_due(video, 2, 0, now)  # chapters but no replay data yet
    assert chapter_service.check_due(video, 0, 5, now)  # replay data but no chapters
    video.chapters_checked_at = now - 23 * HOUR
    assert not chapter_service.check_due(video, 0, 0, now)  # asked less than a day ago
    video.chapters_checked_at = now - 25 * HOUR
    assert chapter_service.check_due(video, 0, 0, now)
    video.upload_date = (now - timedelta(days=14)).date()
    assert not chapter_service.check_due(video, 0, 5, now)  # two weeks: chapters given up on
    assert chapter_service.check_due(video, 0, 0, now)  # ... but replay data still awaited
    assert chapter_service.check_due(video, 2, 0, now)
    video.upload_date = (now - timedelta(days=30)).date()
    assert not chapter_service.check_due(video, 0, 0, now)  # a month: assumed never
    video.upload_date = None
    video.archived_at = now - timedelta(days=2)  # no publish date: counted from archiving
    assert chapter_service.check_due(video, 0, 0, now)
    video.platform = "elsewhere"
    assert not chapter_service.check_due(video, 0, 0, now)


def test_old_and_chaptered_videos_are_not_checked(authed):
    for vid in (WITHOUT, RECENT_CHAPTERED):
        enqueue(authed, vid)
    wait_idle(authed)
    assert detail(authed, WITHOUT)["chapter_check_due"] is False  # published long ago
    assert detail(authed, RECENT_CHAPTERED)["chapter_check_due"] is False
    assert check(authed, WITHOUT) is None
    assert check(authed, RECENT_CHAPTERED) is None


def test_a_recent_video_without_chapters_is_checked_once_a_day(authed):
    enqueue(authed, RECENT)
    wait_idle(authed)
    assert detail(authed, RECENT)["chapter_check_due"] is True

    job = check(authed, RECENT)
    assert job["kind"] == "chapters"
    done = wait_for_job(authed, job["id"])
    assert done["status"] == "completed" and done["result"]["chapters"] == 0
    assert detail(authed, RECENT)["chapter_check_due"] is False
    assert check(authed, RECENT) is None  # nothing is asked again within the day

    set_checked(authed, RECENT, utcnow() - 25 * HOUR)
    assert detail(authed, RECENT)["chapter_check_due"] is True
    assert wait_for_job(authed, check(authed, RECENT)["id"])["status"] == "completed"


def test_chapters_that_appear_later_are_added_to_the_archive(authed):
    enqueue(authed, RECENT_LATE)
    wait_idle(authed)
    assert detail(authed, RECENT_LATE)["chapter_count"] == 0
    flag = Path(os.environ["FAKE_YTDLP_STATE"]) / "chapters_ready"
    flag.write_text("", encoding="utf-8")

    done = wait_for_job(authed, check(authed, RECENT_LATE)["id"])
    assert (done["status"], done["result"]["chapters"], done["result"]["heatmap"]) == (
        "completed",
        2,
        True,
    )
    after = detail(authed, RECENT_LATE)
    assert (after["chapter_count"], after["has_heatmap"], after["chapter_check_due"]) == (
        2,
        True,
        False,
    )
    # info.json changed, and the archive's checksums still agree with it.
    item = next(services(authed).settings.archive_root.glob(f"youtube/{RECENT_LATE}"))
    integrity, _ = verify_dir(item, CancelToken())
    assert integrity == Integrity.OK


def test_a_busy_check_is_not_queued_twice(authed):
    enqueue(authed, RECENT)
    wait_idle(authed)
    with services(authed).sessions.begin() as db:
        policy_service._put_pause(db, policy_service.Pause(utcnow() + 3 * HOUR, "test", 1))
    first = check(authed, RECENT)
    set_checked(authed, RECENT, None)  # as if a day had passed while it waits
    response = authed.post(f"/api/videos/{video_id(authed, RECENT)}/chapters/check")
    assert response.status_code == 409 and response.json()["job_id"] == first["id"]
