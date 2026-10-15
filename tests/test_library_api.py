"""API tests for library browse, detail, thumbnail, and playable media."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings
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


def _seed_archive(tmp_env: Settings) -> None:
    adapter = FakeYtdlpAdapter()
    app = create_app(tmp_env, adapter=adapter, media_processor=FakeMediaProcessor())
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        import time

        for _ in range(50):
            job = client.get(
                f"/api/jobs/{job_id}",
                headers={"Authorization": "Bearer test-token"},
            ).json()
            if job["status"] in {"completed", "failed", "duplicate"}:
                break
            time.sleep(0.05)
        assert job["status"] == "completed"


def test_search_detail_thumbnail_and_play(tmp_env: Settings) -> None:
    _seed_archive(tmp_env)
    app = create_app(
        tmp_env,
        adapter=FakeYtdlpAdapter(),
        media_processor=FakeMediaProcessor(),
    )
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-token"}
        listed = client.get("/api/videos?q=Test", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        detail = client.get("/api/videos/youtube/dQw4w9WgXcQ", headers=headers)
        assert detail.status_code == 200
        body = detail.json()
        assert body["playback"]["mode"] == "remux"
        assert body["has_thumbnail"] is True

        thumb = client.get(
            "/api/videos/youtube/dQw4w9WgXcQ/thumbnail?token=test-token",
        )
        assert thumb.status_code == 200
        assert thumb.content.startswith(b"fake-thumb")

        media = client.get(
            "/api/videos/youtube/dQw4w9WgXcQ/media?variant=play&token=test-token",
        )
        assert media.status_code == 200
        assert media.content == b"webm-bytes"

        denied = client.get("/api/videos/youtube/dQw4w9WgXcQ/media?variant=play")
        assert denied.status_code == 401
