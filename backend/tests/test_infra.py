"""Migrations, events, restart recovery, doctor."""

from __future__ import annotations

import asyncio
import sys
import threading

import pytest
from alembic import command
from conftest import FAKE_YTDLP, wait_for_job
from fastapi.testclient import TestClient

from lones_vdl.db import create_db_engine, make_sessionmaker, upgrade
from lones_vdl.db.migrate import alembic_config
from lones_vdl.db.models import Job, JobStatus
from lones_vdl.events import EventBus
from lones_vdl.main import create_app
from lones_vdl.services.doctor import Doctor
from lones_vdl.ytdlp import YtdlpManager


def test_migrations_match_models(tmp_path):
    engine = create_db_engine(tmp_path / "db.sqlite")
    try:
        upgrade(engine)
        command.check(alembic_config(engine))  # raises if models drifted from migrations
    finally:
        engine.dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_event_bus_fanout_from_threads():
    bus = EventBus(queue_size=2)
    bus.bind(asyncio.get_running_loop())
    async with bus.subscribe() as a, bus.subscribe() as b:
        thread = threading.Thread(target=lambda: bus.publish("job", {"id": 1}))
        thread.start()
        thread.join()
        assert (await asyncio.wait_for(a.get(), 1)).data == {"id": 1}
        assert (await asyncio.wait_for(b.get(), 1)).type == "job"
        for i in range(5):  # overflow drops oldest instead of blocking
            bus.publish("job", {"id": i})
        assert [a.get_nowait().data["id"], a.get_nowait().data["id"]] == [3, 4]
    assert bus.subscriber_count == 0


def test_interrupted_job_resumes_after_restart(settings, fake_state):
    engine = create_db_engine(settings.database_path)
    upgrade(engine)
    with make_sessionmaker(engine).begin() as db:
        db.add(
            Job(
                url="https://www.youtube.com/watch?v=okokokokok1",
                platform="youtube",
                video_id="okokokokok1",
                quality="best",
                status=JobStatus.RUNNING,
                attempts=1,
            )
        )
    engine.dispose()

    app = create_app(settings, ytdlp_command=[sys.executable, str(FAKE_YTDLP)])
    with TestClient(app, headers={"x-lones-vdl": "1"}) as client:
        client.post("/api/auth/setup", json={"password": "correct horse battery"})
        done = wait_for_job(client, 1)
    assert done["status"] == "completed"
    assert done["attempts"] == 1  # the interrupted attempt was not charged


def test_doctor_reports_missing_cookies_and_tests_url(settings, fake_state):
    manager = YtdlpManager(settings, command=[sys.executable, str(FAKE_YTDLP)])
    report = Doctor(settings, manager).run(test_url="https://youtu.be/botbotbot01")
    checks = {c.name: c for c in report.checks}
    assert checks["yt-dlp"].status == "ok" and "2099.01.01" in checks["yt-dlp"].detail
    assert checks["cookies"].status == "fail"
    assert checks["archive"].status in ("ok", "warn")
    assert checks["test download"].status == "fail"
    assert "signed-in" in checks["test download"].detail
    assert not report.ok


def test_doctor_api(authed):
    report = authed.get("/api/system/doctor").json()
    assert {c["name"] for c in report["checks"]} >= {"yt-dlp", "cookies", "ffmpeg", "deno"}
    status = authed.get("/api/system/ytdlp").json()
    assert status["managed"] is False and status["version"] == "2099.01.01"
    assert authed.post("/api/system/ytdlp/update").status_code == 409
