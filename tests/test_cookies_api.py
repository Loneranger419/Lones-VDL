"""API tests for cookie filtering endpoint."""

from pathlib import Path

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter
from tests.test_cookies import SAMPLE

from lones_vdl.app import create_app
from lones_vdl.config import Settings


def test_filter_cookies_endpoint(tmp_env: Settings, tmp_path: Path) -> None:
    cookies = tmp_path / "youtube.cookies.txt"
    cookies.write_text(SAMPLE, encoding="utf-8")
    tmp_env.ytdlp_cookies_file = cookies
    app = create_app(tmp_env, adapter=FakeYtdlpAdapter())
    with TestClient(app) as client:
        denied = client.post("/api/cookies/filter")
        assert denied.status_code == 401

        response = client.post(
            "/api/cookies/filter",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["cookies_before"] == 5
        assert body["cookies_after"] == 2
        assert body["cookies_removed"] == 3
        assert "youtube.com" in body["domains_allowed"]
        assert body["backup_path"]

        cfg = client.get(
            "/api/config",
            headers={"Authorization": "Bearer test-token"},
        ).json()
        assert cfg["cookies_configured"] is True
        assert cfg["cookie_count"] == 2
