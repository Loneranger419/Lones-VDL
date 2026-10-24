"""Tags and filter presets."""

from __future__ import annotations

import json

from conftest import enqueue, services, wait_idle

from lones_vdl.services import tags as tag_service

ASMR_A, ASMR_B = "asmrvideo01", "asmrvideo02"
PLAIN = "plainvid001"


def archive_all(client) -> None:
    for video_id in (ASMR_A, ASMR_B, PLAIN):
        enqueue(client, video_id)
    wait_idle(client)


def titles(client, **params) -> list[str]:
    page = client.get("/api/videos", params=params).json()
    return sorted(v["title"] for v in page["items"])


def test_tags_are_saved_with_the_video_and_deduplicated(authed):
    archive_all(authed)
    items = authed.get("/api/videos").json()["items"]
    video = next(v for v in items if v["video_id"] == ASMR_A)
    detail = authed.get(f"/api/videos/{video['id']}").json()
    assert sorted(detail["tags"]) == ["ASMR", "Sleep"]  # "asmr" repeats ASMR


def test_tag_list_counts_videos(authed):
    archive_all(authed)
    found = {t["tag"]: t for t in authed.get("/api/tags").json()}
    assert found["sleep"]["videos"] == 3 and found["asmr"]["videos"] == 2
    assert found["asmr"]["label"] == "ASMR"
    assert [t["tag"] for t in authed.get("/api/tags", params={"q": "ASM"}).json()] == ["asmr"]


def test_filter_by_tag_and_exclude_tag(authed):
    archive_all(authed)
    assert titles(authed, tag="ASMR") == [f"Title {ASMR_A}", f"Title {ASMR_B}"]
    assert titles(authed, exclude_tag="asmr") == [f"Title {PLAIN}"]
    assert titles(authed, tag="sleep", exclude_tag="fake") == [f"Title {ASMR_A}", f"Title {ASMR_B}"]
    assert titles(authed, tag=["asmr", "fake"]) == []  # must have every tag


def test_presets_hide_tags_and_report_how_many(authed):
    archive_all(authed)
    made = authed.post("/api/presets", json={"name": "No ASMR", "exclude": ["ASMR "]})
    assert made.status_code == 201 and made.json()["exclude"] == ["asmr"]
    preset_id = made.json()["id"]

    # Nothing is hidden until a preset is asked for.
    assert len(titles(authed)) == 3
    page = authed.get("/api/videos", params={"preset": preset_id}).json()
    assert [v["title"] for v in page["items"]] == [f"Title {PLAIN}"]
    assert (page["total"], page["hidden"]) == (1, 2)

    # The default applies when asked for as "default"; "none" turns it off.
    assert authed.put("/api/presets/default", json={"preset_id": preset_id}).status_code == 200
    assert authed.get("/api/videos", params={"preset": "default"}).json()["total"] == 1
    assert authed.get("/api/videos", params={"preset": "none"}).json()["total"] == 3

    # A search with the preset still counts what it hid.
    page = authed.get("/api/videos", params={"preset": "default", "q": "video0"}).json()
    assert (page["total"], page["hidden"]) == (0, 2)


def test_preset_crud_and_default_cleanup(authed):
    a = authed.post("/api/presets", json={"name": "Quiet", "include": ["sleep"]}).json()
    assert authed.post("/api/presets", json={"name": "quiet"}).status_code == 422  # same name
    edited = authed.put(f"/api/presets/{a['id']}", json={"name": "Calm", "exclude": ["fake"]})
    assert edited.json()["name"] == "Calm" and edited.json()["include"] == []
    authed.put("/api/presets/default", json={"preset_id": a["id"]})
    assert authed.get("/api/presets").json()["default_id"] == a["id"]
    assert authed.put("/api/presets/default", json={"preset_id": 999}).status_code == 404
    assert authed.delete(f"/api/presets/{a['id']}").status_code == 204
    assert authed.get("/api/presets").json() == {"presets": [], "default_id": None}
    assert authed.delete(f"/api/presets/{a['id']}").status_code == 404


def test_backfill_reads_tags_of_videos_archived_earlier(authed):
    archive_all(authed)
    svc = services(authed)
    with svc.sessions.begin() as db:
        from lones_vdl.db.models import Video, VideoTag

        for video in db.query(Video):
            video.tags_indexed = False
        db.query(VideoTag).delete()
    assert tag_service.backfill(svc.settings, svc.sessions) == 3
    assert authed.get("/api/tags", params={"q": "asmr"}).json()[0]["videos"] == 2
    assert tag_service.backfill(svc.settings, svc.sessions) == 0  # already indexed


def test_info_json_holds_the_tags(authed):
    archive_all(authed)
    svc = services(authed)
    info = next(svc.settings.archive_root.glob("youtube/*/info.json"))
    assert "tags" in json.loads(info.read_text(encoding="utf-8"))
