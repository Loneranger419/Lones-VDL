from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import delete, func, select

from lones_vdl.api.deps import AuthDep, DbDep, ServicesDep
from lones_vdl.db.models import ACTIVE_JOB_STATUSES, Job, JobStatus
from lones_vdl.schemas import EnqueueRequest, JobOut
from lones_vdl.services import downloads
from lones_vdl.services import jobs as job_service

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[AuthDep])

LOG_TAIL_BYTES = 256 * 1024


def _get(db, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


@router.post("", status_code=status.HTTP_201_CREATED, response_model=JobOut)
def enqueue(body: EnqueueRequest, db: DbDep, services: ServicesDep):
    try:
        job = downloads.enqueue(
            db,
            services.settings,
            body.url,
            body.quality,
            default_quality=services.runtime.current.default_quality,
            watch=body.watch,
            backfill=body.backfill,
            tabs=body.tabs,
        )
    except downloads.EnqueueError as exc:
        return JSONResponse(
            status_code=exc.status,
            content={"detail": exc.message, "kind": exc.kind, **exc.extra},
        )
    db.commit()
    services.bus.publish("job", job_service.job_payload(job))
    services.worker.wake()
    return job


@router.get("", response_model=list[JobOut])
def list_jobs(
    db: DbDep,
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    parent: Annotated[int | None, Query(description="jobs queued by this expand job")] = None,
    channel: Annotated[int | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """Newest first. Active jobs: ?status=queued&status=running."""
    query = select(Job).order_by(Job.id.desc()).offset(offset).limit(limit)
    if status_filter:
        query = query.where(Job.status.in_(status_filter))
    if kind:
        query = query.where(Job.kind.in_(kind))
    if parent is not None:
        query = query.where(Job.parent_pk == parent)
    if channel is not None:
        query = query.where(Job.channel_pk == channel)
    return db.scalars(query).all()


@router.get("/counts")
def job_counts(db: DbDep) -> dict[str, int]:
    """Jobs per status, for badges."""
    return dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: DbDep):
    return _get(db, job_id)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: int, db: DbDep, services: ServicesDep):
    job = _get(db, job_id)
    if job.status == JobStatus.RUNNING:
        # The worker finalises the state once the process has stopped.
        services.worker.cancel_running(job_id)
        return job
    try:
        job_service.cancel_queued(db, job)
    except job_service.JobStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    services.bus.publish("job", job_service.job_payload(job))
    return job


@router.post("/{job_id}/retry", response_model=JobOut)
def retry(job_id: int, db: DbDep, services: ServicesDep):
    job = _get(db, job_id)
    try:
        job_service.retry(db, job)
    except job_service.JobStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    services.bus.publish("job", job_service.job_payload(job))
    services.worker.wake()
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(job_id: int, db: DbDep, services: ServicesDep) -> None:
    job = _get(db, job_id)
    if job.status in ACTIVE_JOB_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "cancel the job first")
    db.execute(delete(Job).where(Job.id == job_id))
    db.commit()
    job_service.log_path(services.settings, job_id).unlink(missing_ok=True)
    services.bus.publish("job.removed", {"id": job_id})


@router.get("/{job_id}/log", response_class=PlainTextResponse)
def job_log(job_id: int, db: DbDep, services: ServicesDep) -> str:
    _get(db, job_id)
    path = job_service.log_path(services.settings, job_id)
    if not path.is_file():
        return ""
    with path.open("rb") as fh:
        size = path.stat().st_size
        fh.seek(max(size - LOG_TAIL_BYTES, 0))
        return fh.read().decode("utf-8", errors="replace")
