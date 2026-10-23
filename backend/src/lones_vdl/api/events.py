from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from lones_vdl.api.deps import AuthDep, ServicesDep

router = APIRouter(tags=["events"], dependencies=[AuthDep])


@router.get("/events", response_class=EventSourceResponse)
async def events(request: Request, services: ServicesDep) -> AsyncIterator[ServerSentEvent]:
    """Live job/video/yt-dlp updates. The UI refetches lists on reconnect."""
    async with services.bus.subscribe() as queue:
        yield ServerSentEvent(event="hello", data={"ok": True}, retry=3000)
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                continue  # EventSourceResponse sends keepalive comments while idle
            yield ServerSentEvent(event=event.type, data=event.data)
