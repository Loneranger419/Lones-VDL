"""API tests for integrity verify/rescan endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings
from lones_vdl.storage import item_paths, write_checksums, write_sidecar


def _seed_disk(archive: Path) -> None:
    paths = item_paths(archive, "youtube", "apiTestVid1")
    paths.final_dir.mkdir(parents=True)
    media = paths.final_dir / "media.mkv"
    media.write_bytes(b"api-media")
    write_checksums(paths, media)
    write_sidecar(
        paths,
        source={
            "id": "apiTestVid1",
            "title": "API Test",
            "webpage_url": "https://youtu.be/apiTestVid1",
        },
        archive={"downloaded_at": "2026-01-02T00:00:00+00:00"},
    )


def test_rescan_and_verify_api(tmp_env: Settings) -> None:
    _seed_disk(tmp_env.archive_root)
    app = create_app(tmp_env, adapter=FakeYtdlpAdapter())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        assert client.post("/api/integrity/rescan").status_code == 401
        rescan = client.post("/api/integrity/rescan", headers=headers)
        assert rescan.status_code == 200
        body = rescan.json()
        assert body["imported"] == 1

        verify = client.post("/api/integrity/verify", headers=headers)
        assert verify.status_code == 200
        assert verify.json()["ok"] == 1
        assert verify.json()["issue_count"] == 0

        videos = client.get("/api/videos", headers=headers).json()
        assert any(v["platform_video_id"] == "apiTestVid1" for v in videos)
