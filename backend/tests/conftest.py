from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lones_vdl.config import Settings
from lones_vdl.main import create_app
from lones_vdl.services import jobs as job_service

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
