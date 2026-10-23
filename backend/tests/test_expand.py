"""Playlists, channels, auto-archive checks, and queue priorities."""

from __future__ import annotations

from datetime import timedelta

from conftest import enqueue, services, set_listings, wait_for_job, wait_idle

from lones_vdl.db import create_db_engine, make_sessionmaker, upgrade, utcnow
from lones_vdl.db.models import Channel, IgnoredVideo, Job, JobKind
from lones_vdl.services import jobs as job_service
from lones_vdl.services.expand import check_job

CHANNEL_URL = "https://www.youtube.com/@fakechannel"
COOKIES = "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsecret\n"


def add(client, url: str, **extra) -> dict:
    response = client.post("/api/jobs", json={"url": url, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def children(client, parent_id: int) -> list[dict]:
    return client.get("/api/jobs", params={"parent": parent_id}).json()


def test_playlist_queues_and_downloads_entries(authed):
    job = add(authed, "https://www.youtube.com/playlist?list=PL1234567890")
    assert (job["kind"], job["priority"]) == ("expand", job_service.PRIORITY_EXPAND)
    done = wait_for_job(authed, job["id"])
    assert done["status"] == "completed", done
    assert done["result"]["queued"] == 1
    assert done["title"] == "Fake Playlist"
    wait_idle(authed)
    [child] = children(authed, job["id"])
    assert child["video_id"] == "okokokokok3"
    assert child["priority"] == job_service.PRIORITY_PLAYLIST
    assert child["status"] == "completed"


def test_channel_backfill_with_watch(authed, fake_state, fake_images, settings):
    set_listings(
        fake_state,
        {
            "videos": ["okokokokok1", "okokokokok2"],
            "streams": [
                "okokokokok4",
                {"id": "livelive001", "live_status": "is_live"},
                {"id": "upcoming001", "live_status": "is_upcoming"},
            ],
        },
    )
    job = add(authed, CHANNEL_URL + "/videos", watch=True, tabs=["videos", "streams", "shorts"])
    done = wait_for_job(authed, job["id"])
    assert done["status"] == "completed", done
    result = done["result"]
    assert (result["found"], result["queued"], result["skipped_live"]) == (3, 3, 2)
    assert result["tabs"] == {"videos": 2, "streams": 1}  # no shorts tab: skipped, not failed
    assert {c["priority"] for c in children(authed, job["id"])} == {job_service.PRIORITY_BACKFILL}
    wait_idle(authed)

    channel = authed.get(f"/api/channels/{done['channel_pk']}").json()
    assert channel["name"] == "Fake Channel"
    assert channel["description"] == "About the fake channel."
    assert channel["watch_enabled"] and channel["watch_shorts"]
    assert channel["video_count"] == 3
    assert channel["last_checked_at"] is not None
    assert channel["has_avatar"] and channel["has_banner"]
    assert "https://yt3.example.com/avatar" in fake_images
    avatar = authed.get(f"/api/channels/{channel['id']}/avatar")
    assert avatar.status_code == 200 and avatar.headers["content-type"] == "image/jpeg"
    assert (settings.archive_root / "youtube/_channels" / channel["channel_id"]).is_dir()


def test_baseline_then_check_queues_only_new_uploads(authed, fake_state):
    set_listings(fake_state, {"videos": ["okokokokok1", "okokokokok2"]})
    job = add(authed, CHANNEL_URL, watch=True, backfill=False, tabs=["videos"])
    done = wait_for_job(authed, job["id"])
    assert (done["result"]["queued"], done["result"]["ignored"]) == (0, 2)
    channel_pk = done["channel_pk"]

    set_listings(fake_state, {"videos": ["newnewnew01", "okokokokok1", "okokokokok2"]})
    check = authed.post(f"/api/channels/{channel_pk}/check")
    assert check.status_code == 201, check.text
    done = wait_for_job(authed, check.json()["id"])
    assert done["result"]["queued"] == 1
    [child] = children(authed, done["id"])
    assert child["video_id"] == "newnewnew01"
    assert child["priority"] == job_service.PRIORITY_NEW_UPLOAD
    wait_idle(authed)

    # A baseline-ignored video can still be added by hand.
    enqueue(authed, "okokokokok1")
    wait_idle(authed)
    assert authed.get("/api/videos").json()["total"] == 2


def test_known_videos_are_not_queued_again(authed, fake_state):
    set_listings(fake_state, {"videos": ["okokokokok1", "okokokokok2"]})
    wait_for_job(authed, enqueue(authed, "okokokokok1")["id"])
    wait_idle(authed)  # includes the channel metadata job
    done = wait_for_job(authed, add(authed, CHANNEL_URL, tabs=["videos"])["id"])
    assert (done["result"]["known"], done["result"]["queued"]) == (1, 1)


def test_duplicate_listing_is_rejected(authed):
    with services(authed).sessions.begin() as db:
        db.add(
            Job(
                kind=JobKind.EXPAND,
                url=CHANNEL_URL,
                platform="youtube",
                quality="best",
                options={"mode": "all"},
                next_attempt_at=utcnow() + timedelta(hours=1),  # stays queued
            )
        )
    again = authed.post("/api/jobs", json={"url": CHANNEL_URL + "/streams"})
    assert again.status_code == 409
    assert again.json()["job_id"] == 1
    bad = authed.post("/api/jobs", json={"url": "https://www.youtube.com/@x", "tabs": ["clips"]})
    assert bad.status_code == 422


def test_failed_children_are_ignored_for_later_checks(authed, fake_state):
    set_listings(fake_state, {"videos": ["gonegone001", "okokokokok1"]})
    done = wait_for_job(authed, add(authed, CHANNEL_URL, tabs=["videos"])["id"])
    wait_idle(authed)
    with services(authed).sessions() as db:
        ignored = {row.video_id: row.reason for row in db.query(IgnoredVideo)}
    assert ignored == {"gonegone001": "unavailable"}
    again = authed.post(f"/api/channels/{done['channel_pk']}/check").json()
    assert wait_for_job(authed, again["id"])["result"]["queued"] == 0


def test_listing_cookie_failure_is_retried_after_import(authed):
    job = add(authed, "https://www.youtube.com/@botchannel")
    done = wait_for_job(authed, job["id"])
    assert done["error_kind"] == "cookies_missing"
    imported = authed.post("/api/cookies", content=COOKIES)
    assert imported.status_code == 200, imported.text
    assert imported.json()["requeued_jobs"] == 1
    done = wait_for_job(authed, job["id"])
    assert done["attempts"] == 1 and done["error_kind"] == "auth_required"


def test_first_download_fetches_channel_details(authed, fake_images):
    wait_for_job(authed, enqueue(authed, "okokokokok1")["id"])
    jobs = wait_idle(authed)
    [meta] = [j for j in jobs if j["kind"] == "expand"]
    assert meta["options"]["mode"] == "meta"
    assert meta["status"] == "completed" and meta["result"]["queued"] == 0
    [channel] = authed.get("/api/channels").json()
    assert channel["has_avatar"] and channel["video_count"] == 1


def test_adding_channel_upgrades_queued_metadata_job(authed, fake_state):
    with services(authed).sessions.begin() as db:
        channel = Channel(platform="youtube", channel_id="UC" + "x" * 22, handle="@fakechannel")
        db.add(channel)
        db.flush()
        db.add(
            Job(
                kind=JobKind.EXPAND,
                url=CHANNEL_URL,
                platform="youtube",
                quality="best",
                channel_pk=channel.id,
                options={"mode": "meta"},
                next_attempt_at=utcnow() + timedelta(hours=1),  # stays queued
            )
        )
    job = add(authed, CHANNEL_URL, tabs=["videos"])
    assert job["id"] == 1 and job["options"]["mode"] == "all"
    done = wait_for_job(authed, 1)  # due now, not in an hour
    assert done["result"]["queued"] == 2
    wait_idle(authed)


def test_enabling_watch_lists_channel_and_scheduler_checks(authed, fake_state):
    set_listings(fake_state, {"videos": ["okokokokok1", "okokokokok2"]})
    with services(authed).sessions.begin() as db:
        db.add(Channel(platform="youtube", channel_id="UC" + "x" * 22, handle="@fakechannel"))
    response = authed.patch("/api/channels/1", json={"watch_enabled": True, "watch_streams": False})
    assert response.status_code == 200, response.text
    jobs = wait_idle(authed)
    [listing] = [j for j in jobs if j["kind"] == "expand"]
    assert listing["options"]["mode"] == "baseline"
    assert listing["options"]["tabs"] == ["videos"]

    scheduler = services(authed).scheduler
    assert scheduler.queue_due() == []  # just checked
    with services(authed).sessions.begin() as db:
        db.get_one(Channel, 1).last_checked_at = utcnow() - timedelta(hours=7)
    [queued] = scheduler.queue_due()
    assert scheduler.queue_due() == []  # one active check per channel
    done = wait_for_job(authed, queued)
    assert done["options"]["mode"] == "recent" and done["result"]["queued"] == 0


def test_claim_order_follows_priority(tmp_path):
    engine = create_db_engine(tmp_path / "db.sqlite")
    upgrade(engine)
    sessions = make_sessionmaker(engine)
    with sessions.begin() as db:
        for vid, priority in (("a", 0), ("b", 100), ("c", 10), ("d", 100)):
            db.add(
                Job(url=vid, platform="youtube", video_id=vid, quality="best", priority=priority)
            )
        db.add(Job(kind=JobKind.EXPAND, url="x", platform="youtube", quality="best", priority=999))
    order = []
    with sessions.begin() as db:
        while (job := job_service.claim_next(db, [JobKind.DOWNLOAD])) is not None:
            order.append(job.video_id)
    assert order == ["b", "d", "c", "a"]
    engine.dispose()


def test_check_job_uses_channel_watch_settings():
    channel = Channel(
        id=5,
        platform="youtube",
        channel_id="UC" + "y" * 22,
        handle="@someone",
        watch_videos=True,
        watch_streams=False,
        watch_shorts=True,
        watch_quality="720",
    )
    job = check_job(channel, quality="best", max_attempts=3)
    assert job.url == "https://www.youtube.com/@someone"
    assert job.quality == "720"
    assert job.options["tabs"] == ["videos", "shorts"]
