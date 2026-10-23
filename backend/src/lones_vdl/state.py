"""Long-lived services wired together once per app instance (stored on app.state)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import create_db_engine, make_sessionmaker, upgrade
from lones_vdl.events import EventBus
from lones_vdl.jobs.worker import Worker
from lones_vdl.jobs.ytdlp_updates import YtdlpUpdater
from lones_vdl.services.auth import LoginThrottle
from lones_vdl.services.downloads import DownloadPipeline
from lones_vdl.services.jobs import JobReporter
from lones_vdl.ytdlp import YtdlpManager


@dataclass
class Services:
    settings: Settings
    engine: Engine
    sessions: sessionmaker
    bus: EventBus
    ytdlp: YtdlpManager
    reporter: JobReporter
    pipeline: DownloadPipeline
    worker: Worker
    updater: YtdlpUpdater
    throttle: LoginThrottle = field(default_factory=LoginThrottle)

    @classmethod
    def build(cls, settings: Settings, *, ytdlp_command: list[str] | None = None) -> Services:
        for path in (settings.data_dir, settings.secrets_dir, settings.archive_root):
            path.mkdir(parents=True, exist_ok=True)
        engine = create_db_engine(settings.database_path)
        upgrade(engine)
        sessions = make_sessionmaker(engine)
        bus = EventBus()
        ytdlp = YtdlpManager(settings, command=ytdlp_command)
        reporter = JobReporter(sessions, bus)
        pipeline = DownloadPipeline(settings, sessions, ytdlp, reporter)
        worker = Worker(
            concurrency=settings.download_concurrency,
            sessions=sessions,
            pipeline=pipeline,
            reporter=reporter,
            ytdlp=ytdlp,
        )
        updater = YtdlpUpdater(settings, ytdlp, sessions, bus, on_installed=worker.wake)
        return cls(
            settings=settings,
            engine=engine,
            sessions=sessions,
            bus=bus,
            ytdlp=ytdlp,
            reporter=reporter,
            pipeline=pipeline,
            worker=worker,
            updater=updater,
        )

    async def start(self) -> None:
        self.bus.bind(asyncio.get_running_loop())
        await self.worker.start()
        await self.updater.start()

    async def stop(self) -> None:
        await self.updater.stop()
        await self.worker.stop()
        self.engine.dispose()
