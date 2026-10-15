"""API tests for job enqueue and auth."""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings


def _client(tmp_env: Settings, adapter: FakeYtdlpAdapter | None = None) -> TestClient:
    app = create_app(tmp_env, adapter=adapter or FakeYtdlpAdapter())
    return TestClient(app)


def test_health_still_public(tmp_env: Settings) -> None:
    with _client(tmp_env) as client:
        response = client.get("/api/health")
        assert response.status_code == 200


def test_enqueue_requires_token(tmp_env: Settings) -> None:
    with _client(tmp_env) as client:
        response = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert response.status_code == 401


def test_enqueue_and_complete(tmp_env: Settings) -> None:
    adapter = FakeYtdlpAdapter()
    with _client(tmp_env, adapter) as client:
        # Disable background race: process via service after enqueue with sync path
        # Enqueue starts background worker; wait by polling job status.
        response = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]

        import time

        job = response.json()
        for _ in range(50):
            job = client.get(
                f"/api/jobs/{job_id}",
                headers={"Authorization": "Bearer test-token"},
            ).json()
            if job["status"] in {"completed", "failed", "duplicate"}:
                break
            time.sleep(0.05)
        assert job["status"] == "completed"

        videos = client.get(
            "/api/videos",
            headers={"Authorization": "Bearer test-token"},
        ).json()
        assert len(videos) == 1
        assert videos[0]["platform_video_id"] == "dQw4w9WgXcQ"

        dup = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"Authorization": "Bearer test-token"},
        )
        assert dup.status_code == 409
