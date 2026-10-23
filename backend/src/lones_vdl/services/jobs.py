"""Job state changes. Every change is committed and broadcast as an event."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Iterable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import ACTIVE_JOB_STATUSES, Job, JobKind, JobStage, JobStatus
from lones_vdl.events import EventBus
from lones_vdl.schemas import JobOut, JobProgress
from lones_vdl.ytdlp import ErrorKind

# Higher runs first within a worker lane.
PRIORITY_MANUAL = 100  # a single video added by hand
PRIORITY_EXPAND = 50  # listing a playlist/channel the user just added
PRIORITY_WATCH_CHECK = 30  # scheduled channel check
PRIORITY_PLAYLIST = 20  # videos from a playlist
PRIORITY_NEW_UPLOAD = 10  # new videos found by a channel check
PRIORITY_BACKFILL = 0  # a channel's back catalogue

# Failures that a fresh cookie import can fix.
COOKIE_ERRORS = (ErrorKind.COOKIES_MISSING, ErrorKind.COOKIES_INVALID)


def log_path(settings: Settings, job_id: int) -> Path:
    return settings.job_logs_dir / f"{job_id}.log"


@contextlib.contextmanager
def open_job_log(settings: Settings, job: Job) -> Iterator[TextIO]:
    """Append to the job's log, starting with an attempt header."""
    path = log_path(settings, job.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(f"\n===== attempt {job.attempts} at {utcnow().isoformat()} =====\n")
        log.write(f"{job.kind} url={job.url} quality={job.quality}\n")
        yield log


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


def active_expand_for_url(db: DbSession, url: str) -> Job | None:
    return db.scalars(
        select(Job).where(
            Job.kind == JobKind.EXPAND, Job.url == url, Job.status.in_(ACTIVE_JOB_STATUSES)
        )
    ).first()


def claim_next(db: DbSession, kinds: Iterable[str]) -> Job | None:
    """Mark the next due queued job of these kinds as running. Single process: no locking."""
    job = db.scalars(
        select(Job)
        .where(
            Job.status == JobStatus.QUEUED,
            Job.kind.in_(list(kinds)),
            Job.next_attempt_at <= utcnow(),
        )
        .order_by(Job.priority.desc(), Job.next_attempt_at, Job.id)
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


def seconds_until_next_due(db: DbSession, kinds: Iterable[str]) -> float | None:
    when = db.scalars(
        select(Job.next_attempt_at)
        .where(Job.status == JobStatus.QUEUED, Job.kind.in_(list(kinds)))
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
    if job.kind == JobKind.EXPAND and active_expand_for_url(db, job.url):
        raise JobStateError("this playlist/channel is already being listed")
    requeue(job)


def requeue(job: Job) -> None:
    job.status = JobStatus.QUEUED
    job.stage = JobStage.WAITING
    job.attempts = 0
    job.progress = None
    job.error_kind = None
    job.error_message = None
    job.next_attempt_at = utcnow()
    job.finished_at = None


def requeue_cookie_failures(db: DbSession) -> list[Job]:
    """After a cookie import: retry jobs that failed only because of cookies."""
    jobs = db.scalars(
        select(Job).where(Job.status == JobStatus.FAILED, Job.error_kind.in_(COOKIE_ERRORS))
    ).all()
    requeued = []
    for job in jobs:
        if job.video_id and active_job_for(db, job.platform, job.video_id):
            continue
        if job.kind == JobKind.EXPAND and active_expand_for_url(db, job.url):
            continue
        requeue(job)
        db.flush()
        requeued.append(job)
    return requeued
