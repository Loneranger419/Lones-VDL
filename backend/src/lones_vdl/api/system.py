from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from lones_vdl.api.deps import AuthDep, ServicesDep
from lones_vdl.schemas import DoctorReport, YtdlpStatus
from lones_vdl.services.doctor import Doctor
from lones_vdl.ytdlp import YtdlpError

router = APIRouter(prefix="/system", tags=["system"], dependencies=[AuthDep])


@router.get("/doctor")
async def doctor(
    services: ServicesDep, url: Annotated[str | None, Query(max_length=500)] = None
) -> DoctorReport:
    """Environment checks; with ?url= also resolves that video (no media download)."""
    return await run_in_threadpool(Doctor(services.settings, services.ytdlp).run, test_url=url)


@router.get("/ytdlp")
async def ytdlp_status(services: ServicesDep) -> YtdlpStatus:
    return await run_in_threadpool(services.updater.status)


@router.post("/ytdlp/update")
async def ytdlp_update(services: ServicesDep) -> YtdlpStatus:
    """Install/upgrade yt-dlp now. Waits for running downloads to finish first."""
    if not services.ytdlp.managed:
        raise HTTPException(status.HTTP_409_CONFLICT, "yt-dlp is externally managed")
    try:
        await services.updater.update_now()
    except YtdlpError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.message) from exc
    return await run_in_threadpool(services.updater.status)
