"""Durable job queue: jobs live in SQLite; this loop claims and runs them in threads.

Jobs run in lanes so slow work never blocks the rest: downloads (configurable concurrency),
listing playlists/channels (one at a time), and maintenance such as verify/rescan (one).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import sessionmaker

from lones_vdl.db import utcnow
from lones_vdl.db.models import Job, JobKind, JobStage, JobStatus
from lones_vdl.events import Wakeup
from lones_vdl.services import channels as channel_service
from lones_vdl.services import cookies as cookie_service
from lones_vdl.services import jobs as job_service
from lones_vdl.services.jobs import JobReporter
from lones_vdl.storage import archive
from lones_vdl.ytdlp import Cancelled, CancelToken, ErrorKind, YtdlpError, YtdlpManager
from lones_vdl.ytdlp.errors import MESSAGES, RETRYABLE, error_lines

logger = logging.getLogger(__name__)

IDLE_POLL_SECONDS = 30.0

# A video found by a playlist/channel listing that fails like this is ignored, so later
# channel checks do not queue it again. A manual request clears the ignore.
IGNORE_CHILD_ON = {
    ErrorKind.UNAVAILABLE: "unavailable",
    ErrorKind.AUTH_REQUIRED: "auth_required",
    ErrorKind.FORMAT_UNAVAILABLE: "format_unavailable",
    ErrorKind.UNSUPPORTED: "unsupported",
}


class Pipeline(Protocol):
    def run(self, job_id: int, cancel: CancelToken) -> dict[str, Any]:
        """Run one attempt; return fields to set on the completed job. Raise on failure."""
        ...

    def cleanup(self, job_id: int) -> None:
        """Remove temporary files once the job is finished for good."""
        ...


@dataclass
class Lane:
    name: str
    kinds: tuple[str, ...]
    concurrency: Callable[[], int]
    needs_ytdlp: bool = True
    running: set[int] = field(default_factory=set)


def default_lanes(download_concurrency: Callable[[], int]) -> list[Lane]:
    return [
        Lane("download", (JobKind.DOWNLOAD,), download_concurrency),
        Lane("listing", (JobKind.EXPAND,), lambda: 1),
        Lane("maintenance", (JobKind.VERIFY, JobKind.RESCAN), lambda: 1, needs_ytdlp=False),
    ]


class Worker:
    def __init__(
        self,
        *,
        sessions: sessionmaker,
        reporter: JobReporter,
        ytdlp: YtdlpManager,
        pipelines: dict[str, Pipeline],
        lanes: list[Lane],
    ) -> None:
        self.sessions = sessions
        self.reporter = reporter
        self.ytdlp = ytdlp
        self.pipelines = pipelines
        self.lanes = lanes
        self._tokens: dict[int, CancelToken] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._wake = Wakeup()
        self._stopping = False
        self._loop_task: asyncio.Task[None] | None = None

    @property
    def running_job_ids(self) -> list[int]:
        return list(self._tokens)

    async def start(self) -> None:
        self._wake.bind(asyncio.get_running_loop())
        with self.sessions.begin() as db:
            recovered = job_service.recover_interrupted(db)
        if recovered:
            logger.info("requeued interrupted jobs: %s", recovered)
        self._loop_task = asyncio.create_task(self._loop(), name="job-worker")

    async def stop(self) -> None:
        self._stopping = True
        for token in self._tokens.values():
            token.cancel()
        self._wake.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def wake(self) -> None:
        """Safe from any thread."""
        self._wake.set()

    def cancel_running(self, job_id: int) -> bool:
        token = self._tokens.get(job_id)
        if token is None:
            return False
        token.cancel()
        return True

    def _has_capacity(self, lane: Lane) -> bool:
        return len(lane.running) < lane.concurrency() and (
            not lane.needs_ytdlp or self.ytdlp.installed
        )

    async def _loop(self) -> None:
        while not self._stopping:
            self._wake.clear()
            for lane in self.lanes:
                while self._has_capacity(lane):
                    claimed = await asyncio.to_thread(self._claim, lane.kinds)
                    if claimed is None:
                        break
                    job_id, kind = claimed
                    token = CancelToken()
                    self._tokens[job_id] = token
                    lane.running.add(job_id)
                    task = asyncio.create_task(
                        self._execute(lane, job_id, kind, token), name=f"job-{job_id}"
                    )
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            kinds = [k for lane in self.lanes if self._has_capacity(lane) for k in lane.kinds]
            timeout = await asyncio.to_thread(self._next_due, kinds)
            await self._wake.wait(timeout)

    def _claim(self, kinds: tuple[str, ...]) -> tuple[int, str] | None:
        with self.sessions.begin() as db:
            job = job_service.claim_next(db, kinds)
        if job is None:
            return None
        self.reporter.bus.publish("job", job_service.job_payload(job))
        return job.id, job.kind

    def _next_due(self, kinds: list[str]) -> float:
        if not kinds:
            return IDLE_POLL_SECONDS
        with self.sessions() as db:
            due = job_service.seconds_until_next_due(db, kinds)
        return IDLE_POLL_SECONDS if due is None else min(max(due, 0.05), IDLE_POLL_SECONDS)

    async def _execute(self, lane: Lane, job_id: int, kind: str, token: CancelToken) -> None:
        try:
            await asyncio.to_thread(self._process, job_id, kind, token)
        finally:
            self._tokens.pop(job_id, None)
            lane.running.discard(job_id)
            self.reporter.forget(job_id)
            self._wake.set()

    def _process(self, job_id: int, kind: str, token: CancelToken) -> None:
        pipeline = self.pipelines[kind]
        try:
            fields = pipeline.run(job_id, token)
        except Cancelled:
            self._cancelled(job_id, pipeline)
        except YtdlpError as exc:
            self._failed(job_id, pipeline, exc.kind, exc.detail)
        except archive.ArchiveConflict as exc:
            self._failed(job_id, pipeline, ErrorKind.CONFLICT, str(exc))
        except Exception as exc:  # noqa: BLE001 - a job must never take down the worker
            logger.exception("job %s crashed", job_id)
            self._failed(job_id, pipeline, ErrorKind.UNKNOWN, f"{type(exc).__name__}: {exc}")
        else:
            self.reporter.update(
                job_id,
                status=JobStatus.COMPLETED,
                stage=JobStage.DONE,
                progress=1.0,
                error_kind=None,
                error_message=None,
                finished_at=utcnow(),
                **fields,
            )
            pipeline.cleanup(job_id)
            if fields.get("video_pk"):
                self.reporter.bus.publish("video", {"id": fields["video_pk"], "job_id": job_id})

    def _cancelled(self, job_id: int, pipeline: Pipeline) -> None:
        if self._stopping:
            # Shutdown, not a user cancel: keep partial files so the next start resumes.
            with self.sessions.begin() as db:
                job = db.get_one(Job, job_id)
                job.status = JobStatus.QUEUED
                job.stage = JobStage.WAITING
                job.attempts = max(job.attempts - 1, 0)
            return
        self.reporter.update(
            job_id, status=JobStatus.CANCELLED, stage=JobStage.DONE, finished_at=utcnow()
        )
        pipeline.cleanup(job_id)

    def _failed(self, job_id: int, pipeline: Pipeline, kind: ErrorKind, detail: str) -> None:
        with self.sessions() as db:
            job = db.get_one(Job, job_id)
        message = MESSAGES[kind]
        if kind == ErrorKind.COOKIES_INVALID:
            # Before the job's new status, so whoever reacts to it sees the cookie state too.
            with self.sessions.begin() as db:
                cookie_service.record_health(db, cookie_service.INVALID, message)
        if kind in RETRYABLE and job.attempts < job.max_attempts:
            self.reporter.update(
                job_id,
                status=JobStatus.QUEUED,
                stage=JobStage.WAITING,
                error_kind=kind,
                error_message=message,
                next_attempt_at=utcnow() + job_service.retry_delay(job.attempts),
            )
        else:
            self.reporter.update(
                job_id,
                status=JobStatus.FAILED,
                stage=JobStage.DONE,
                error_kind=kind,
                error_message=message,
                finished_at=utcnow(),
            )
            pipeline.cleanup(job_id)
            if job.parent_pk is not None and job.video_id and kind in IGNORE_CHILD_ON:
                with self.sessions.begin() as db:
                    channel_service.ignore(db, job.platform, job.video_id, IGNORE_CHILD_ON[kind])
        lines = error_lines(detail, limit=1) or detail.strip().splitlines()[-1:]
        logger.warning("job %s %s: %s", job_id, kind, lines[0][:300] if lines else "")
