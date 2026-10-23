"""Job state changes. Every change is committed and broadcast as an event."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.db import utcnow
from lones_vdl.db.models import ACTIVE_JOB_STATUSES, Job, JobStage, JobStatus
from lones_vdl.events import EventBus
from lones_vdl.schemas import JobOut, JobProgress


def job_payload(job: Job) -> dict[str, Any]:
    return JobOut.model_validate(job).model_dump(mode="json")


def retry_delay(attempt: int) -> timedelta:
    """1 min, 4 min, 16 min, ... capped at 2 h."""
    return timedelta(seconds=min(60 * 4 ** max(attempt - 1, 0), 2 * 60 * 60))


class JobReporter:
    # Progress events are rate-limited per job; DB writes of progress even more so.
    EVENT_INTERVAL = 0.25
    DB_INTERVAL = 5.0

    def __init__(self, sessions: sessionmaker, bus: EventBus) -> None:
        self.sessions = sessions
        self.bus = bus
        self._last_event: dict[int, float] = {}
        self._last_db: dict[int, float] = {}
        self._lock = threading.Lock()

    def update(self, job_id: int, **fields: Any) -> Job:
        with self.sessions.begin() as db:
            job = db.get_one(Job, job_id)
            for name, value in fields.items():
                setattr(job, name, value)
        self.bus.publish("job", job_payload(job))
        return job

    def progress(self, update: JobProgress, *, force: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_event.get(update.id, 0) < self.EVENT_INTERVAL:
                return
            self._last_event[update.id] = now
            write_db = force or now - self._last_db.get(update.id, 0) >= self.DB_INTERVAL
            if write_db:
                self._last_db[update.id] = now
        if write_db:
            with self.sessions.begin() as db:
                job = db.get_one(Job, update.id)
                job.stage = update.stage
                job.progress = update.progress
        self.bus.publish("job.progress", update.model_dump(mode="json"))

    def forget(self, job_id: int) -> None:
        with self._lock:
            self._last_event.pop(job_id, None)
            self._last_db.pop(job_id, None)


class JobStateError(Exception):
    pass


def active_job_for(db: DbSession, platform: str, video_id: str) -> Job | None:
    return db.scalars(
        select(Job).where(
            Job.platform == platform,
            Job.video_id == video_id,
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
    ).first()


def claim_next(db: DbSession) -> Job | None:
    """Mark the next due queued job as running. Single-process: no row locking needed."""
    job = db.scalars(
        select(Job)
        .where(Job.status == JobStatus.QUEUED, Job.next_attempt_at <= utcnow())
        .order_by(Job.next_attempt_at, Job.id)
        .limit(1)
    ).first()
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.stage = JobStage.WAITING
    job.attempts += 1
    job.started_at = utcnow()
    job.progress = None
    return job


def seconds_until_next_due(db: DbSession) -> float | None:
    when = db.scalars(
        select(Job.next_attempt_at)
        .where(Job.status == JobStatus.QUEUED)
        .order_by(Job.next_attempt_at)
        .limit(1)
    ).first()
    if when is None:
        return None
    return max((when - utcnow()).total_seconds(), 0.0)


def recover_interrupted(db: DbSession) -> list[int]:
    """Requeue jobs left 'running' by a crash or restart, without charging an attempt."""
    jobs = db.scalars(select(Job).where(Job.status == JobStatus.RUNNING)).all()
    for job in jobs:
        job.status = JobStatus.QUEUED
        job.stage = JobStage.WAITING
        job.attempts = max(job.attempts - 1, 0)
        job.next_attempt_at = utcnow()
    return [job.id for job in jobs]


def cancel_queued(db: DbSession, job: Job) -> None:
    if job.status != JobStatus.QUEUED:
        raise JobStateError(f"job is {job.status}")
    job.status = JobStatus.CANCELLED
    job.stage = JobStage.DONE
    job.finished_at = utcnow()


def retry(db: DbSession, job: Job) -> None:
    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise JobStateError(f"job is {job.status}")
    if job.video_id and active_job_for(db, job.platform, job.video_id):
        raise JobStateError("another job for this video is active")
    job.status = JobStatus.QUEUED
    job.stage = JobStage.WAITING
    job.attempts = 0
    job.progress = None
    job.error_kind = None
    job.error_message = None
    job.next_attempt_at = utcnow()
    job.finished_at = None
