"""In-process pub/sub feeding the SSE endpoint. Publish is safe from any thread."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    type: str  # e.g. "job", "job.progress", "video", "ytdlp"
    data: dict[str, Any]


class EventBus:
    def __init__(self, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type: str, data: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        event = Event(type, data)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._fanout(event)
        else:
            loop.call_soon_threadsafe(self._fanout, event)

    def _fanout(self, event: Event) -> None:
        for queue in list(self._subscribers):
            if queue.full():  # slow client: drop its oldest event rather than block everyone
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(event)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class Wakeup:
    """An asyncio.Event for background loops that may be set from any thread (sync routes
    run in a threadpool, where asyncio.Event.set is unsafe)."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._event.set()
        else:
            loop.call_soon_threadsafe(self._event.set)

    def clear(self) -> None:
        self._event.clear()

    async def wait(self, timeout: float | None = None) -> None:
        """Return when set or after timeout (None = no timeout)."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._event.wait(), timeout)
