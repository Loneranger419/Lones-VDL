"""API tests for cookie upload endpoint."""

from pathlib import Path

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter
from tests.test_cookies import SAMPLE

from lones_vdl.app import create_app
from lones_vdl.config import Settings


def test_upload_cookies_endpoint(tmp_env: Settings, tmp_path: Path) -> None:
    cookies = tmp_path / "secrets" / "cookies.txt"
    tmp_env.ytdlp_cookies_file = cookies
    app = create_app(tmp_env, adapter=FakeYtdlpAdapter())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        denied = client.post(
            "/api/cookies/upload",
            files={"file": ("cookies.txt", SAMPLE, "text/plain")},
        )
        assert denied.status_code == 401

        cfg = client.get("/api/config", headers=headers).json()
        assert cfg["cookies_path_configured"] is True
        assert cfg["cookies_configured"] is False

        response = client.post(
            "/api/cookies/upload",
            headers=headers,
            files={"file": ("cookies.txt", SAMPLE, "text/plain")},
        )
        assert response.status_code == 200
        body = response.json()
        assert "VISITOR_INFO1_LIVE" not in response.text
        assert body["filtered"] is True
        assert body["cookies_after_filter"] == 3
        assert body["cookies_removed"] == 2
        assert cookies.is_file()
        text = cookies.read_text(encoding="utf-8")
        assert "youtube.com" in text
        assert "twitch.tv" in text
        assert "chatgpt.com" not in text

        cfg = client.get("/api/config", headers=headers).json()
        assert cfg["cookies_configured"] is True
        assert cfg["cookie_count"] == 3


def test_upload_rejects_garbage(tmp_env: Settings, tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    tmp_env.ytdlp_cookies_file = cookies
    app = create_app(tmp_env, adapter=FakeYtdlpAdapter())
    with TestClient(app) as client:
        response = client.post(
            "/api/cookies/upload",
            headers={"Authorization": "Bearer test-token"},
            files={"file": ("cookies.txt", "not a cookie file\n", "text/plain")},
        )
        assert response.status_code == 400


def test_upload_requires_configured_path(tmp_env: Settings) -> None:
    tmp_env.ytdlp_cookies_file = None
    app = create_app(tmp_env, adapter=FakeYtdlpAdapter())
    with TestClient(app) as client:
        response = client.post(
            "/api/cookies/upload",
            headers={"Authorization": "Bearer test-token"},
            files={"file": ("cookies.txt", SAMPLE, "text/plain")},
        )
        assert response.status_code == 400
        assert "not configured" in response.json()["detail"].lower()
