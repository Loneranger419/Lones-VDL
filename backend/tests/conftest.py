from __future__ import annotations

import json
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lones_vdl.config import Settings
from lones_vdl.main import create_app
from lones_vdl.services import accounts as account_service
from lones_vdl.services import channels as channel_service
from lones_vdl.services import jobs as job_service
from lones_vdl.services import policy as policy_service

FAKE_YTDLP = Path(__file__).parent / "fake_ytdlp.py"
PASSWORD = "correct horse battery"
TERMINAL = ("completed", "failed", "cancelled")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        archive_root=tmp_path / "archive",
        frontend_dist=tmp_path / "no-frontend",
        ytdlp_update_interval_hours=0,
        # The download policy's real pacing would make every test wait.
        video_delay_min_seconds=0,
        video_delay_max_seconds=0,
    )


@pytest.fixture
def fake_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "fake-state"
    state.mkdir()
    monkeypatch.setenv("FAKE_YTDLP_STATE", str(state))
    return state


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_service, "retry_delay", lambda attempt: timedelta(0))


@pytest.fixture(autouse=True)
def instant_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Policy waits are seconds in production; tests that exercise them set their own."""
    monkeypatch.setattr(policy_service, "DELAY_FLOOR", 0.0)
    monkeypatch.setattr(policy_service, "AUTH_GAP_SECONDS", 0.0)
    monkeypatch.setattr(policy_service, "BACKOFF_SECONDS", (0.0,))


@pytest.fixture(autouse=True)
def fake_images(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Channel artwork downloads never touch the network in tests."""
    fetched: list[str] = []

    def fetch(url: str) -> tuple[bytes, str]:
        fetched.append(url)
        return b"\xff\xd8\xff fake jpeg", "image/jpeg"

    monkeypatch.setattr(channel_service, "fetch_bytes", fetch)
    return fetched


@pytest.fixture
def client(settings: Settings, fake_state: Path):
    app = create_app(settings, ytdlp_command=[sys.executable, str(FAKE_YTDLP)])
    with TestClient(app, headers={"x-lones-vdl": "1"}) as test_client:
        yield test_client


@pytest.fixture
def authed(client: TestClient) -> TestClient:
    response = client.post("/api/auth/setup", json={"password": PASSWORD})
    assert response.status_code == 204, response.text
    return client


def wait_for_job(client: TestClient, job_id: int, statuses=TERMINAL, timeout: float = 20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} stuck: {job}")


def enqueue(client: TestClient, video_id: str, **extra) -> dict:
    response = client.post("/api/jobs", json={"url": f"https://youtu.be/{video_id}", **extra})
    assert response.status_code == 201, response.text
    return response.json()


def wait_until(predicate, timeout: float = 20, message: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {message}")


def wait_idle(client: TestClient, timeout: float = 30) -> list[dict]:
    """Wait until no job is queued or running; returns all jobs."""
    wait_until(
        lambda: not client.get("/api/jobs", params={"status": ["queued", "running"]}).json(),
        timeout,
        "the queue to drain",
    )
    return client.get("/api/jobs", params={"limit": 500}).json()


def set_listings(fake_state: Path, listings: dict) -> None:
    (fake_state / "listings.json").write_text(json.dumps(listings), encoding="utf-8")


def services(client: TestClient):
    return client.app.state.services


COOKIES = (
    "# Netscape HTTP Cookie File\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsecret\n"
    ".paypal.com\tTRUE\t/\tTRUE\t4102444800\tx\ty\n"
)
# The fake yt-dlp treats cookies holding this name as a channel membership.
MEMBER_COOKIES = COOKIES + ".youtube.com\tTRUE\t/\tTRUE\t4102444800\tMEMBERSHIP\t1\n"


def add_account(
    client: TestClient, label: str = "Alternate", role: str = "alternate", text=COOKIES
):
    """Create an account with cookies directly through the service layer."""
    svc = services(client)
    with svc.sessions.begin() as db:
        account = account_service.create(db, label, role)
        account_service.import_cookies(svc.settings, account, text)
        return account.id


def youtube_limits(status: dict) -> dict:
    """The YouTube entry of a policy status, with the videos group's numbers at the top level."""
    youtube = next(p for p in status["platforms"] if p["platform"] == "youtube")
    groups = {g["key"]: g for g in youtube["groups"]}
    videos = groups["videos"]
    return {
        **youtube,
        "downloads_24h": videos["used"],
        "authenticated_24h": videos["auth_used"],
        "daily_download_cap": videos["cap"],
        "daily_auth_cap": videos["auth_cap"],
        "shorts": groups["shorts"],
    }


def account_health(client: TestClient, account_id: int) -> str | None:
    """The health status the API reports for one account."""
    account = next(a for a in client.get("/api/accounts").json() if a["id"] == account_id)
    health = account["status"]["health"]
    return health["status"] if health else None


def calls(fake_state: Path) -> list[str]:
    """Resolve calls the fake yt-dlp saw, as 'video_id anon|auth', oldest first."""
    path = fake_state / "calls"
    return path.read_text().splitlines() if path.exists() else []
