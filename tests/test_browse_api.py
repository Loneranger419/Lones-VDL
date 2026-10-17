"""Browse, channels, favorites, related, and metadata refresh APIs."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings
from lones_vdl.db import Database
from lones_vdl.media import ProbeResult, StreamInfo


class FakeMediaProcessor:
    def probe(self, path: Path) -> ProbeResult:
        return ProbeResult(
            format_name="matroska,webm",
            streams=[
                StreamInfo("video", "av1"),
                StreamInfo("audio", "opus"),
            ],
        )

    def remux_copy(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"webm-bytes")


def _wait_completed(client: TestClient, job_id: str, headers: dict[str, str]) -> dict:
    for _ in range(50):
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in {"completed", "failed", "duplicate"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _seed_two_videos(tmp_env: Settings) -> None:
    adapter_a = FakeYtdlpAdapter(video_id="vidAAAAAAA", title="Alpha Video")
    adapter_b = FakeYtdlpAdapter(video_id="vidBBBBBBB", title="Beta Video")
    # First job with adapter A
    app = create_app(tmp_env, adapter=adapter_a, media_processor=FakeMediaProcessor())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=vidAAAAAAA"},
            headers=headers,
        )
        assert r.status_code == 202
        assert _wait_completed(client, r.json()["id"], headers)["status"] == "completed"

    app = create_app(tmp_env, adapter=adapter_b, media_processor=FakeMediaProcessor())
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=vidBBBBBBB"},
            headers=headers,
        )
        assert r.status_code == 202
        assert _wait_completed(client, r.json()["id"], headers)["status"] == "completed"


def test_list_sort_channels_favorites_related(tmp_env: Settings) -> None:
    _seed_two_videos(tmp_env)
    app = create_app(
        tmp_env,
        adapter=FakeYtdlpAdapter(),
        media_processor=FakeMediaProcessor(),
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        listed = client.get("/api/videos?sort=title&order=asc", headers=headers)
        assert listed.status_code == 200
        titles = [v["title"] for v in listed.json()]
        assert titles == ["Alpha Video", "Beta Video"]
        for video in listed.json():
            assert video["channel"] == "Test Channel"
            assert video["channel_id"] == "UC_test_channel"
            assert video["upload_date"] == "20091025"
            assert video["metadata_incomplete"] is False

        page1 = client.get(
            "/api/videos?sort=title&order=asc&limit=1&offset=0",
            headers=headers,
        )
        assert page1.status_code == 200
        assert [v["title"] for v in page1.json()] == ["Alpha Video"]
        page2 = client.get(
            "/api/videos?sort=title&order=asc&limit=1&offset=1",
            headers=headers,
        )
        assert page2.status_code == 200
        assert [v["title"] for v in page2.json()] == ["Beta Video"]
        past_end = client.get(
            "/api/videos?sort=title&order=asc&limit=1&offset=2",
            headers=headers,
        )
        assert past_end.status_code == 200
        assert past_end.json() == []

        channels = client.get("/api/channels", headers=headers)
        assert channels.status_code == 200
        body = channels.json()
        assert len(body) == 1
        assert body[0]["channel_id"] == "UC_test_channel"
        assert body[0]["video_count"] == 2
        assert body[0]["favorited"] is False
        assert body[0]["has_thumbnail"] is True

        thumb = client.get(
            "/api/channels/youtube/UC_test_channel/thumbnail?token=test-token",
        )
        assert thumb.status_code == 200
        assert thumb.content == b"fake-channel-avatar"

        fav = client.put(
            "/api/channels/youtube/UC_test_channel/favorite",
            json={"favorited": True, "channel": "Test Channel"},
            headers=headers,
        )
        assert fav.status_code == 200
        assert fav.json()["favorited"] is True

        channels = client.get("/api/channels", headers=headers).json()
        assert channels[0]["favorited"] is True

        filtered = client.get(
            "/api/videos?channel=youtube:UC_test_channel&sort=title&order=asc",
            headers=headers,
        )
        assert filtered.status_code == 200
        assert len(filtered.json()) == 2

        related = client.get(
            "/api/videos/youtube/vidAAAAAAA/related",
            headers=headers,
        )
        assert related.status_code == 200
        assert len(related.json()) == 1
        assert related.json()[0]["platform_video_id"] == "vidBBBBBBB"


def test_refresh_fills_missing_upload_date(tmp_env: Settings) -> None:
    db = Database(tmp_env.database_path)
    db.insert_video(
        platform="youtube",
        platform_video_id="needDate1",
        title="Needs Date",
        url="https://www.youtube.com/watch?v=needDate1",
        media_relpath="youtube/needDate1/media.mkv",
        metadata_relpath="youtube/needDate1/metadata.json",
        checksum_sha256="abc",
        channel="Test Channel",
        channel_id="UC_test_channel",
        upload_date=None,
        metadata_incomplete=True,
        metadata_gaps=["upload_date"],
    )
    db.close()

    adapter = FakeYtdlpAdapter(video_id="needDate1", title="Needs Date")
    app = create_app(tmp_env, adapter=adapter, media_processor=FakeMediaProcessor())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        result = client.post(
            "/api/videos/youtube/needDate1/refresh",
            headers=headers,
        )
        assert result.status_code == 200
        body = result.json()
        assert body["status"] in {"ok", "partial"}
        assert "upload_date" not in body["gaps"] or body["status"] == "ok"

        listed = client.get("/api/videos?q=Needs", headers=headers)
        assert listed.status_code == 200
        row = listed.json()[0]
        assert row["upload_date"] == "20091025"
        assert row["metadata_incomplete"] is False
