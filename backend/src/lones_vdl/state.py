"""Long-lived services wired together once per app instance (stored on app.state)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import create_db_engine, make_sessionmaker, upgrade
from lones_vdl.db.models import JobKind
from lones_vdl.events import EventBus
from lones_vdl.jobs.scheduler import ChannelScheduler
from lones_vdl.jobs.worker import Worker, default_lanes
from lones_vdl.jobs.ytdlp_updates import YtdlpUpdater
from lones_vdl.services import accounts as account_service
from lones_vdl.services.auth import LoginThrottle
from lones_vdl.services.downloads import DownloadPipeline
from lones_vdl.services.expand import ExpandPipeline
from lones_vdl.services.integrity import RescanPipeline, VerifyPipeline
from lones_vdl.services.jobs import JobReporter
from lones_vdl.services.policy import Policy
from lones_vdl.services.runtime import RuntimeConfig
from lones_vdl.services.subtitles import SubtitlesPipeline
from lones_vdl.ytdlp import YtdlpManager


@dataclass
class Services:
    settings: Settings
    runtime: RuntimeConfig
    policy: Policy
    engine: Engine
    sessions: sessionmaker
    bus: EventBus
    ytdlp: YtdlpManager
    reporter: JobReporter
    worker: Worker
    scheduler: ChannelScheduler
    updater: YtdlpUpdater
    throttle: LoginThrottle = field(default_factory=LoginThrottle)

    @classmethod
    def build(cls, settings: Settings, *, ytdlp_command: list[str] | None = None) -> Services:
        for path in (settings.data_dir, settings.secrets_dir, settings.archive_root):
            path.mkdir(parents=True, exist_ok=True)
        engine = create_db_engine(settings.database_path)
        upgrade(engine)
        sessions = make_sessionmaker(engine)
        with sessions.begin() as db:
            account_service.adopt_legacy_cookies(settings, db)
        runtime = RuntimeConfig(settings, sessions)
        policy = Policy(settings, runtime, sessions)
        bus = EventBus()
        ytdlp = YtdlpManager(settings, command=ytdlp_command)
        reporter = JobReporter(sessions, bus)
        worker = Worker(
            sessions=sessions,
            reporter=reporter,
            ytdlp=ytdlp,
            pipelines={
                JobKind.DOWNLOAD: DownloadPipeline(settings, sessions, ytdlp, reporter, policy),
                JobKind.EXPAND: ExpandPipeline(settings, sessions, ytdlp, reporter, policy),
                JobKind.SUBTITLES: SubtitlesPipeline(settings, sessions, ytdlp, reporter, policy),
                JobKind.VERIFY: VerifyPipeline(settings, sessions, reporter),
                JobKind.RESCAN: RescanPipeline(settings, sessions, reporter),
            },
            lanes=default_lanes(),
            policy=policy,
        )
        scheduler = ChannelScheduler(settings, runtime, sessions, bus, on_queued=worker.wake)
        updater = YtdlpUpdater(settings, runtime, ytdlp, sessions, bus, on_installed=worker.wake)
        return cls(
            settings=settings,
            runtime=runtime,
            policy=policy,
            engine=engine,
            sessions=sessions,
            bus=bus,
            ytdlp=ytdlp,
            reporter=reporter,
            worker=worker,
            scheduler=scheduler,
            updater=updater,
        )

    async def start(self) -> None:
        self.bus.bind(asyncio.get_running_loop())
        await self.worker.start()
        await self.scheduler.start()
        await self.updater.start()

    async def stop(self) -> None:
        await self.updater.stop()
        await self.scheduler.stop()
        await self.worker.stop()
        self.engine.dispose()
