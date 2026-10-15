"""Smoke tests for the health endpoint."""

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl import __version__
from lones_vdl.app import create_app
from lones_vdl.config import Settings


def test_health_returns_ok(tmp_path) -> None:
    settings = Settings(
        api_token="test-token",
        archive_root=tmp_path / "archive",
        database_path=tmp_path / "test.db",
    )
    with TestClient(create_app(settings, adapter=FakeYtdlpAdapter())) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["version"] == __version__
