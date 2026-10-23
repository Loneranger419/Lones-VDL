"""Library browsing, watch progress, media streaming, deletion, collections, creators."""

from __future__ import annotations

import pytest
from conftest import enqueue, wait_idle

IDS = ("okokokokok1", "okokokokok2", "okokokokok3")


@pytest.fixture
def library(authed):
    for vid in IDS:
        enqueue(authed, vid)
    wait_idle(authed)
    page = authed.get("/api/videos", params={"sort": "archived_asc"}).json()
    assert page["total"] == 3
    return {v["video_id"]: v["id"] for v in page["items"]}


def video_ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [v["video_id"] for v in response.json()["items"]]


def test_search_filter_sort_and_paging(authed, library):
    assert video_ids(authed.get("/api/videos", params={"q": "title okokokokok2"})) == [IDS[1]]
    assert len(video_ids(authed.get("/api/videos", params={"q": "fake channel"}))) == 3
    assert video_ids(authed.get("/api/videos", params={"q": "100%_nothing"})) == []
    assert video_ids(authed.get("/api/videos", params={"sort": "archived_asc"})) == list(IDS)
    page = authed.get("/api/videos", params={"limit": 2, "offset": 2, "sort": "archived_asc"})
    assert video_ids(page) == [IDS[2]] and page.json()["total"] == 3
    assert video_ids(authed.get("/api/videos", params={"kind": "short"})) == []
    channel = authed.get("/api/channels").json()[0]["id"]
    assert len(video_ids(authed.get("/api/videos", params={"channel": channel}))) == 3
    assert authed.get("/api/videos", params={"sort": "nope"}).status_code == 422


def test_progress_continue_and_watched(authed, library):
    pk = library[IDS[0]]
    assert (
        authed.put(f"/api/videos/{pk}/progress", json={"position_seconds": 20}).status_code == 204
    )
    [cont] = authed.get("/api/videos/continue").json()
    assert (cont["id"], cont["position_seconds"], cont["watched"]) == (pk, 20, False)
    in_progress = authed.get("/api/videos", params={"watch": "in_progress"})
    assert video_ids(in_progress) == [IDS[0]]

    # 90% of the 63 s duration marks it watched; it leaves "continue watching".
    authed.put(f"/api/videos/{pk}/progress", json={"position_seconds": 58})
    assert authed.get(f"/api/videos/{pk}").json()["watched"] is True
    assert authed.get("/api/videos/continue").json() == []
    assert video_ids(authed.get("/api/videos", params={"watch": "watched"})) == [IDS[0]]
    assert len(video_ids(authed.get("/api/videos", params={"watch": "unwatched"}))) == 2

    unwatched = authed.put(f"/api/videos/{pk}/watched", json={"watched": False}).json()
    assert (unwatched["watched"], unwatched["position_seconds"]) == (False, 0)
    assert authed.put(f"/api/videos/{pk}/watched", json={"watched": True}).json()["watched"]


def test_related_up_next(authed, library):
    related = authed.get(f"/api/videos/{library[IDS[0]]}/related").json()
    assert related["up_next"]["video_id"] == IDS[1]  # same upload date: next by id
    assert {v["video_id"] for v in related["more_from_channel"]} == {IDS[2]}


def test_media_range_thumbnail_and_subtitles(authed, library):
    pk = library[IDS[0]]
    full = authed.get(f"/api/videos/{pk}/media")
    assert full.status_code == 200
    assert full.headers["content-type"] == "video/webm"
    assert full.headers["accept-ranges"] == "bytes"
    partial = authed.get(f"/api/videos/{pk}/media", headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206
    assert partial.content == b"\x1aE\xdf\xa3"
    assert partial.headers["content-range"] == f"bytes 0-3/{len(full.content)}"

    assert authed.get(f"/api/videos/{pk}/thumbnail").headers["content-type"] == "image/jpeg"
    detail = authed.get(f"/api/videos/{pk}").json()
    assert detail["subtitles"] == ["en"]
    sub = authed.get(f"/api/videos/{pk}/subtitles/en.vtt")
    assert sub.status_code == 200 and sub.text.startswith("WEBVTT")
    assert sub.headers["content-type"].startswith("text/vtt")
    assert authed.get(f"/api/videos/{pk}/subtitles/..%2Finfo.vtt").status_code == 404
    assert authed.get(f"/api/videos/{pk}/subtitles/de.vtt").status_code == 404


def test_media_requires_login(client):
    client.post("/api/auth/setup", json={"password": "correct horse battery"})
    client.post("/api/auth/logout")
    assert client.get("/api/videos/1/media").status_code == 401


def test_delete_video_removes_files_and_blocks_requeue(authed, library, settings, fake_state):
    pk = library[IDS[0]]
    assert authed.delete(f"/api/videos/{pk}").status_code == 204
    assert not (settings.archive_root / "youtube" / IDS[0]).exists()
    assert authed.get(f"/api/videos/{pk}").status_code == 404
    # A channel listing skips it ...
    channel_url = "https://www.youtube.com/@fakechannel"
    job = authed.post("/api/jobs", json={"url": channel_url, "tabs": ["videos"]}).json()
    jobs = wait_idle(authed)
    listing = next(j for j in jobs if j["id"] == job["id"])
    assert listing["result"]["queued"] == 0  # okokokokok1 deleted, okokokokok2 archived
    # ... but adding it by hand works.
    enqueue(authed, IDS[0])
    wait_idle(authed)
    assert authed.get("/api/videos").json()["total"] == 3


def test_delete_can_keep_files(authed, library, settings):
    pk = library[IDS[1]]
    authed.delete(f"/api/videos/{pk}", params={"delete_files": "false"})
    assert (settings.archive_root / "youtube" / IDS[1] / "media.webm").exists()


def test_collections(authed, library):
    created = authed.post("/api/collections", json={"name": "Favourites"})
    assert created.status_code == 201
    cid = created.json()["id"]
    pks = [library[v] for v in IDS]

    added = authed.post(f"/api/collections/{cid}/items", json={"video_ids": [pks[2], pks[0]]})
    assert [v["id"] for v in added.json()["videos"]] == [pks[2], pks[0]]
    again = authed.post(f"/api/collections/{cid}/items", json={"video_ids": [pks[0], pks[1]]})
    assert [v["id"] for v in again.json()["videos"]] == [pks[2], pks[0], pks[1]]
    bad = authed.post(f"/api/collections/{cid}/items", json={"video_ids": [999]})
    assert bad.status_code == 422

    order = authed.put(f"/api/collections/{cid}/items", json={"video_ids": pks})
    assert [v["id"] for v in order.json()["videos"]] == pks
    partial_order = authed.put(f"/api/collections/{cid}/items", json={"video_ids": pks[:2]})
    assert partial_order.status_code == 422

    [summary] = authed.get("/api/collections").json()
    assert (summary["item_count"], summary["cover_video_pk"]) == (3, pks[0])
    assert authed.get(f"/api/videos/{pks[0]}").json()["collection_ids"] == [cid]

    removed = authed.delete(f"/api/collections/{cid}/items/{pks[0]}").json()
    assert [v["id"] for v in removed["videos"]] == pks[1:]
    renamed = authed.patch(f"/api/collections/{cid}", json={"name": "Best", "description": "x"})
    assert (renamed.json()["name"], renamed.json()["description"]) == ("Best", "x")

    # Deleting a video drops it from collections; deleting a collection keeps videos.
    authed.delete(f"/api/videos/{pks[1]}")
    assert [v["id"] for v in authed.get(f"/api/collections/{cid}").json()["videos"]] == [pks[2]]
    assert authed.delete(f"/api/collections/{cid}").status_code == 204
    assert authed.get("/api/videos").json()["total"] == 2


def test_creators(authed, library):
    channel = authed.get("/api/channels").json()[0]
    created = authed.post(
        "/api/creators", json={"name": "Fake Person", "channel_ids": [channel["id"]]}
    )
    assert created.status_code == 201, created.text
    creator = created.json()
    assert creator["video_count"] == 3
    assert [c["id"] for c in creator["channels"]] == [channel["id"]]
    assert authed.get(f"/api/channels/{channel['id']}").json()["creator_pk"] == creator["id"]
    by_creator = authed.get("/api/videos", params={"creator": creator["id"]})
    assert len(video_ids(by_creator)) == 3

    dupe = authed.post("/api/creators", json={"name": "fake person"})
    assert dupe.status_code == 409
    assert authed.post("/api/creators", json={"name": "X", "channel_ids": [99]}).status_code == 422

    patched = authed.patch(f"/api/creators/{creator['id']}", json={"channel_ids": [], "notes": "n"})
    assert patched.json()["channels"] == [] and patched.json()["notes"] == "n"
    linked = authed.patch(f"/api/channels/{channel['id']}", json={"creator_id": creator["id"]})
    assert linked.json()["creator_pk"] == creator["id"]
    assert authed.delete(f"/api/creators/{creator['id']}").status_code == 204
    assert authed.get(f"/api/channels/{channel['id']}").json()["creator_pk"] is None


def test_stats(authed, library):
    stats = authed.get("/api/system/stats").json()
    assert stats["videos"] == 3 and stats["channels"] == 1
    assert stats["total_bytes"] == 3 * 4000
    assert stats["by_integrity"] == {"unverified": 3}
    assert stats["jobs"]["completed"] >= 3
    assert stats["archive_free_bytes"] > 0
