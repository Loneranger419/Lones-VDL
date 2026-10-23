"""Queue a check for new uploads on each auto-archived channel every N hours."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import Channel
from lones_vdl.events import EventBus, Wakeup
from lones_vdl.services import channels as channel_service
from lones_vdl.services import jobs as job_service
from lones_vdl.services.expand import check_job
from lones_vdl.services.runtime import RuntimeConfig

logger = logging.getLogger(__name__)

POLL_SECONDS = 300.0


class ChannelScheduler:
    def __init__(
        self,
        settings: Settings,
        runtime: RuntimeConfig,
        sessions: sessionmaker,
        bus: EventBus,
        *,
        on_queued: Callable[[], None],
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self.sessions = sessions
        self.bus = bus
        self.on_queued = on_queued
        self._wake = Wakeup()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._wake.bind(asyncio.get_running_loop())
        self._task = asyncio.create_task(self._loop(), name="channel-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def wake(self) -> None:
        """Re-evaluate now (e.g. after the interval setting changed). Safe from any thread."""
        self._wake.set()

    def queue_due(self) -> list[int]:
        """Create check jobs for watched channels whose last check is older than the interval."""
        interval = self.runtime.current.channel_watch_interval_hours
        if interval <= 0:
            return []
        cutoff = utcnow() - timedelta(hours=interval)
        jobs = []
        with self.sessions.begin() as db:
            channels = db.scalars(
                select(Channel).where(
                    Channel.watch_enabled.is_(True),
                    or_(Channel.last_checked_at.is_(None), Channel.last_checked_at <= cutoff),
                )
            ).all()
            for channel in channels:
                if not channel_service.enabled_tabs(channel):
                    continue
                if channel_service.active_expand_for_channel(db, channel.id) is not None:
                    continue
                job = check_job(
                    channel,
                    quality=self.runtime.current.default_quality,
                    max_attempts=self.settings.download_max_attempts,
                )
                db.add(job)
                db.flush()
                jobs.append(job)
        for job in jobs:
            self.bus.publish("job", job_service.job_payload(job))
        if jobs:
            logger.info("queued channel checks: %s", [job.id for job in jobs])
            self.on_queued()
        return [job.id for job in jobs]

    async def _loop(self) -> None:
        while True:
            self._wake.clear()
            try:
                await asyncio.to_thread(self.queue_due)
            except Exception:  # noqa: BLE001 - keep scheduling after a transient DB error
                logger.exception("channel check scheduling failed")
            await self._wake.wait(POLL_SECONDS)
