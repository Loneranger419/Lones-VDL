"""Integrity verify, archive rescan, cookie management, runtime settings."""

from __future__ import annotations

import shutil
import sys

from conftest import FAKE_YTDLP, PASSWORD, enqueue, services, wait_for_job, wait_idle
from fastapi.testclient import TestClient

from lones_vdl.db.models import JobKind, Video
from lones_vdl.main import create_app
from lones_vdl.services.integrity import enqueue_maintenance

COOKIES = (
    "# Netscape HTTP Cookie File\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsupersecretvalue\n"
    ".youtube.com\tTRUE\t/\tTRUE\t4102444800\tPREF\tf6=40000000\n"
    ".google.com\tTRUE\t/\tTRUE\t4102444800\tNID\tgooglesecret\n"
)


def archived(client, *ids: str) -> dict[str, int]:
    for vid in ids:
        enqueue(client, vid)
    wait_idle(client)
    return {v["video_id"]: v["id"] for v in client.get("/api/videos").json()["items"]}


def run_maintenance(client, kind: str, **body) -> dict:
    response = client.post(f"/api/system/{kind}", json=body or None)
    assert response.status_code == 201, response.text
    done = wait_for_job(client, response.json()["id"])
    assert done["status"] == "completed", done
    return done["result"]


def test_verify_detects_ok_mismatch_and_missing(authed, settings):
    pks = archived(authed, "okokokokok1", "okokokokok2", "okokokokok3")
    root = settings.archive_root / "youtube"
    (root / "okokokokok2" / "media.webm").write_bytes(b"bit rot")
    (root / "okokokokok3" / "thumbnail.jpg").unlink()

    result = run_maintenance(authed, "verify")
    assert (result["checked"], result["ok"], result["mismatch"], result["missing"]) == (3, 1, 1, 1)
    states = {vid: authed.get(f"/api/videos/{pk}").json()["integrity"] for vid, pk in pks.items()}
    assert states == {"okokokokok1": "ok", "okokokokok2": "mismatch", "okokokokok3": "missing"}
    assert authed.get("/api/videos", params={"integrity": "mismatch"}).json()["total"] == 1

    subset = run_maintenance(authed, "verify", video_ids=[pks["okokokokok1"]])
    assert subset["checked"] == 1


def test_rescan_reindexes_and_flags_missing(authed, settings):
    archived(authed, "okokokokok1", "okokokokok2", "okokokokok3")
    with services(authed).sessions.begin() as db:
        db.delete(db.query(Video).filter_by(video_id="okokokokok1").one())
        db.query(Video).filter_by(video_id="okokokokok3").one().channel_pk = None
    settings.partial_dir.joinpath("999").mkdir(parents=True)
    shutil.rmtree(settings.archive_root / "youtube" / "okokokokok2")

    result = run_maintenance(authed, "rescan")
    assert (result["indexed"], result["missing"], result["stale_partials_removed"]) == (1, 1, 1)
    assert result["relinked"] == 1
    page = authed.get("/api/videos").json()
    restored = next(v for v in page["items"] if v["video_id"] == "okokokokok1")
    assert restored["title"] == "Title okokokokok1"
    assert restored["channel"]["handle"] == "@fakechannel"
    gone = next(v for v in page["items"] if v["video_id"] == "okokokokok2")
    assert gone["integrity"] == "missing"
    relinked = next(v for v in page["items"] if v["video_id"] == "okokokokok3")
    assert relinked["channel"]["handle"] == "@fakechannel"


def test_cookie_import_status_test_and_delete(authed, settings):
    empty = authed.get("/api/cookies").json()
    assert empty["present"] is False

    imported = authed.post("/api/cookies", content=COOKIES, headers={"content-type": "text/plain"})
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert "supersecretvalue" not in imported.text and "googlesecret" not in imported.text
    assert body["summary"]["kept"] == 2 and body["summary"]["dropped_domain"] == 1
    assert body["status"]["login_cookies"] == {"SID": "2100-01-01"}
    assert body["status"]["health"]["status"] == "untested"
    assert "NID" not in settings.cookies_file.read_text()

    status = authed.get("/api/cookies")
    assert "supersecretvalue" not in status.text
    assert status.json()["cookie_count"] == 2

    tested = authed.post("/api/cookies/test").json()
    assert tested["status"] == "ok"
    settings.cookie_test_url = "https://youtu.be/rotrotrot01"
    assert authed.post("/api/cookies/test").json()["status"] == "invalid"

    assert authed.post("/api/cookies", content="not cookies").status_code == 422
    assert authed.post("/api/cookies", content="x" * (1024 * 1024 + 1)).status_code == 413
    assert authed.delete("/api/cookies").status_code == 204
    gone = authed.get("/api/cookies").json()
    assert gone["present"] is False and gone["health"]["status"] == "missing"


def test_download_outcomes_update_cookie_health(authed):
    authed.post("/api/cookies", content=COOKIES)
    wait_for_job(authed, enqueue(authed, "okokokokok1")["id"])
    assert authed.get("/api/cookies").json()["health"]["status"] == "ok"
    wait_for_job(authed, enqueue(authed, "rotrotrot01")["id"])
    assert authed.get("/api/cookies").json()["health"]["status"] == "invalid"


def test_cookie_import_requeues_cookie_failures(authed):
    failed = wait_for_job(authed, enqueue(authed, "botbotbot01")["id"])
    assert failed["error_kind"] == "cookies_missing"
    other = wait_for_job(authed, enqueue(authed, "gonegone001")["id"])
    imported = authed.post("/api/cookies", content=COOKIES).json()
    assert imported["requeued_jobs"] == 1
    assert wait_for_job(authed, failed["id"])["error_kind"] == "auth_required"
    assert authed.get(f"/api/jobs/{other['id']}").json()["attempts"] == 1


def test_runtime_settings_persist(authed, settings, fake_state):
    current = authed.get("/api/settings").json()
    assert current["current"]["download_concurrency"] == 1
    assert current["defaults"]["default_quality"] == "best"

    patched = authed.patch(
        "/api/settings", json={"download_concurrency": 3, "default_quality": "720"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["current"]["download_concurrency"] == 3
    assert authed.patch("/api/settings", json={"default_quality": "8k"}).status_code == 422
    assert authed.patch("/api/settings", json={"download_concurrency": 99}).status_code == 422

    # New downloads use the runtime default quality.
    assert enqueue(authed, "okokokokok1")["quality"] == "720"

    app = create_app(settings, ytdlp_command=[sys.executable, str(FAKE_YTDLP)])
    with TestClient(app, headers={"x-lones-vdl": "1"}) as again:
        again.post("/api/auth/login", json={"password": PASSWORD})
        assert again.get("/api/settings").json()["current"]["download_concurrency"] == 3


def test_maintenance_conflict(authed):
    with services(authed).sessions.begin() as db:
        enqueue_maintenance(db, JobKind.RESCAN).status = "running"
    assert authed.post("/api/system/rescan").status_code == 409
