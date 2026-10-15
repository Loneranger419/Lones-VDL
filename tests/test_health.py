"""Smoke tests for the Milestone 0 health endpoint."""

from fastapi.testclient import TestClient

from lones_vdl import __version__
from lones_vdl.app import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
