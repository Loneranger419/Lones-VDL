"""Keep the managed yt-dlp installed and current."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.events import EventBus
from lones_vdl.schemas import YtdlpStatus
from lones_vdl.services import settings_store
from lones_vdl.ytdlp import YtdlpError, YtdlpManager
from lones_vdl.ytdlp.manager import UpdateResult

logger = logging.getLogger(__name__)

RETRY_AFTER_FAILURE = timedelta(hours=1)


class YtdlpUpdater:
    def __init__(
        self,
        settings: Settings,
        manager: YtdlpManager,
        sessions: sessionmaker,
        bus: EventBus,
        *,
        on_installed=None,
    ) -> None:
        self.settings = settings
        self.manager = manager
        self.sessions = sessions
        self.bus = bus
        self.on_installed = on_installed
        self.updating = False
        self.last_error: str | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def status(self) -> YtdlpStatus:
        with self.sessions() as db:
            last = settings_store.get_datetime(db, settings_store.YTDLP_LAST_CHECK)
        return YtdlpStatus(
            managed=self.manager.managed,
            installed=self.manager.installed,
            version=self.manager.version(),
            channel=self.settings.ytdlp_channel,
            updating=self.updating,
            last_checked_at=last,
            last_error=self.last_error,
        )

    async def start(self) -> None:
        if self.manager.managed:
            self._task = asyncio.create_task(self._loop(), name="ytdlp-updater")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def update_now(self) -> UpdateResult:
        async with self._lock:
            self.updating = True
            self.bus.publish("ytdlp", self.status().model_dump(mode="json"))
            try:
                result = await asyncio.to_thread(self.manager.install_or_update)
                self.last_error = None
                return result
            except YtdlpError as exc:
                self.last_error = exc.detail[-500:] or exc.message
                raise
            finally:
                self.updating = False
                with self.sessions.begin() as db:
                    settings_store.put(db, settings_store.YTDLP_LAST_CHECK, utcnow().isoformat())
                self.bus.publish("ytdlp", self.status().model_dump(mode="json"))
                if self.manager.installed and self.on_installed is not None:
                    self.on_installed()

    def _next_check(self) -> datetime | None:
        interval = self.settings.ytdlp_update_interval_hours
        if not self.manager.installed:
            return utcnow()
        if interval <= 0:
            return None
        with self.sessions() as db:
            last = settings_store.get_datetime(db, settings_store.YTDLP_LAST_CHECK)
        if last is None:
            return utcnow()
        wait = RETRY_AFTER_FAILURE if self.last_error else timedelta(hours=interval)
        return last + wait

    async def _loop(self) -> None:
        while True:
            when = self._next_check()
            if when is None:
                return
            delay = (when - utcnow()).total_seconds()
            if delay > 0:
                await asyncio.sleep(min(delay, 3600))
                continue
            try:
                await self.update_now()
            except YtdlpError as exc:
                logger.error("yt-dlp install/update failed: %s", exc.detail[-500:])
