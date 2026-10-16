"""API tests for public (non-secret) config used by the web UI."""

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings


def test_config_requires_token_and_hides_secrets(tmp_env: Settings) -> None:
    app = create_app(tmp_env, adapter=FakeYtdlpAdapter())
    with TestClient(app) as client:
        assert client.get("/api/config").status_code == 401
        response = client.get(
            "/api/config",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["default_quality"] == "best"
        assert "archive" in body["archive_root"].replace("\\", "/")
        assert body["cookies_configured"] is False
        assert body["cookie_platforms"] == ["youtube"]
        assert body["cookie_count"] is None
        assert "best" in body["quality_presets"]
        assert "api_token" not in body
