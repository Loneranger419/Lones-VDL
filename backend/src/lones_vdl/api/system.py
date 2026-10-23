from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from lones_vdl.api.deps import AuthDep, DbDep, ServicesDep
from lones_vdl.db.models import Job, JobKind
from lones_vdl.schemas import DoctorReport, JobOut, StatsOut, VerifyRequest, YtdlpStatus
from lones_vdl.services import integrity, library
from lones_vdl.services import jobs as job_service
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


@router.get("/stats", response_model=StatsOut)
def stats(db: DbDep, services: ServicesDep):
    return library.stats(db, services.settings)


def _maintenance(db, services, kind: JobKind, video_ids: list[int] | None = None) -> Job:
    try:
        job = integrity.enqueue_maintenance(db, kind, video_ids=video_ids)
    except integrity.MaintenanceBusy as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    services.bus.publish("job", job_service.job_payload(job))
    services.worker.wake()
    return job


@router.post("/verify", status_code=status.HTTP_201_CREATED, response_model=JobOut)
def verify(db: DbDep, services: ServicesDep, body: VerifyRequest | None = None):
    """Re-hash archived files against their checksums.json (slow on large archives)."""
    return _maintenance(db, services, JobKind.VERIFY, body.video_ids if body else None)


@router.post("/rescan", status_code=status.HTTP_201_CREATED, response_model=JobOut)
def rescan(db: DbDep, services: ServicesDep):
    """Index archive folders missing from the DB and flag DB entries whose files are gone."""
    return _maintenance(db, services, JobKind.RESCAN)
