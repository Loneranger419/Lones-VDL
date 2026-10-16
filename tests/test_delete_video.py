"""Delete archived video: DB row + on-disk item directory."""

from __future__ import annotations

import time
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
            streams=[StreamInfo("video", "av1"), StreamInfo("audio", "opus")],
        )

    def remux_copy(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"webm-bytes")


def _wait(client: TestClient, job_id: str, headers: dict[str, str]) -> dict:
    for _ in range(50):
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in {"completed", "failed", "duplicate"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_delete_removes_db_and_disk(tmp_env: Settings) -> None:
    adapter = FakeYtdlpAdapter(video_id="delVid00001", title="Delete Me")
    app = create_app(tmp_env, adapter=adapter, media_processor=FakeMediaProcessor())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=delVid00001"},
            headers=headers,
        )
        assert r.status_code == 202
        assert _wait(client, r.json()["id"], headers)["status"] == "completed"

        item_dir = tmp_env.archive_root / "youtube" / "delVid00001"
        assert item_dir.is_dir()
        assert (item_dir / "metadata.json").is_file()

        deleted = client.delete("/api/videos/youtube/delVid00001", headers=headers)
        assert deleted.status_code == 204

        listed = client.get("/api/videos", headers=headers)
        assert listed.status_code == 200
        assert listed.json() == []

        assert not item_dir.exists()

        missing = client.delete("/api/videos/youtube/delVid00001", headers=headers)
        assert missing.status_code == 404
