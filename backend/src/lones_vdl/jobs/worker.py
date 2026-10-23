"""Durable download queue: jobs live in SQLite; this loop claims and runs them in threads."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy.orm import sessionmaker

from lones_vdl.db import utcnow
from lones_vdl.db.models import Job, JobStage, JobStatus
from lones_vdl.services import jobs as job_service
from lones_vdl.services.downloads import DownloadPipeline
from lones_vdl.services.jobs import JobReporter
from lones_vdl.storage import archive
from lones_vdl.ytdlp import Cancelled, CancelToken, ErrorKind, YtdlpError, YtdlpManager
from lones_vdl.ytdlp.errors import MESSAGES, RETRYABLE, error_lines

logger = logging.getLogger(__name__)

IDLE_POLL_SECONDS = 30.0


class Worker:
    def __init__(
        self,
        *,
        concurrency: int,
        sessions: sessionmaker,
        pipeline: DownloadPipeline,
        reporter: JobReporter,
        ytdlp: YtdlpManager,
    ) -> None:
        self.concurrency = concurrency
        self.sessions = sessions
        self.pipeline = pipeline
        self.reporter = reporter
        self.ytdlp = ytdlp
        self._running: dict[int, CancelToken] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._wake = asyncio.Event()
        self._stopping = False
        self._loop_task: asyncio.Task[None] | None = None

    @property
    def running_job_ids(self) -> list[int]:
        return list(self._running)

    async def start(self) -> None:
        with self.sessions.begin() as db:
            recovered = job_service.recover_interrupted(db)
        if recovered:
            logger.info("requeued interrupted jobs: %s", recovered)
        self._loop_task = asyncio.create_task(self._loop(), name="download-worker")

    async def stop(self) -> None:
        self._stopping = True
        for token in self._running.values():
            token.cancel()
        self._wake.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def wake(self) -> None:
        self._wake.set()

    def cancel_running(self, job_id: int) -> bool:
        token = self._running.get(job_id)
        if token is None:
            return False
        token.cancel()
        return True

    async def _loop(self) -> None:
        while not self._stopping:
            self._wake.clear()
            while len(self._running) < self.concurrency and self.ytdlp.installed:
                job_id = await asyncio.to_thread(self._claim)
                if job_id is None:
                    break
                token = CancelToken()
                self._running[job_id] = token
                task = asyncio.create_task(self._execute(job_id, token), name=f"job-{job_id}")
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            timeout = await asyncio.to_thread(self._next_due)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout)

    def _claim(self) -> int | None:
        with self.sessions.begin() as db:
            job = job_service.claim_next(db)
        if job is None:
            return None
        self.reporter.bus.publish("job", job_service.job_payload(job))
        return job.id

    def _next_due(self) -> float:
        with self.sessions() as db:
            due = job_service.seconds_until_next_due(db)
        return IDLE_POLL_SECONDS if due is None else min(max(due, 0.05), IDLE_POLL_SECONDS)

    async def _execute(self, job_id: int, token: CancelToken) -> None:
        try:
            await asyncio.to_thread(self._process, job_id, token)
        finally:
            self._running.pop(job_id, None)
            self.reporter.forget(job_id)
            self._wake.set()

    def _process(self, job_id: int, token: CancelToken) -> None:
        try:
            video_pk = self.pipeline.run(job_id, token)
        except Cancelled:
            self._cancelled(job_id)
        except YtdlpError as exc:
            self._failed(job_id, exc.kind, exc.detail)
        except archive.ArchiveConflict as exc:
            self._failed(job_id, ErrorKind.CONFLICT, str(exc))
        except Exception as exc:  # noqa: BLE001 - a job must never take down the worker
            logger.exception("job %s crashed", job_id)
            self._failed(job_id, ErrorKind.UNKNOWN, f"{type(exc).__name__}: {exc}")
        else:
            self.reporter.update(
                job_id,
                status=JobStatus.COMPLETED,
                stage=JobStage.DONE,
                progress=1.0,
                video_pk=video_pk,
                error_kind=None,
                error_message=None,
                finished_at=utcnow(),
            )
            archive.remove_partial(self.pipeline.workdir(job_id))
            self.reporter.bus.publish("video", {"id": video_pk, "job_id": job_id})

    def _cancelled(self, job_id: int) -> None:
        if self._stopping:
            # Shutdown, not a user cancel: keep the partial dir so the next start resumes.
            with self.sessions.begin() as db:
                job = db.get_one(Job, job_id)
                job.status = JobStatus.QUEUED
                job.stage = JobStage.WAITING
                job.attempts = max(job.attempts - 1, 0)
            return
        self.reporter.update(
            job_id, status=JobStatus.CANCELLED, stage=JobStage.DONE, finished_at=utcnow()
        )
        archive.remove_partial(self.pipeline.workdir(job_id))

    def _failed(self, job_id: int, kind: ErrorKind, detail: str) -> None:
        with self.sessions() as db:
            job = db.get_one(Job, job_id)
        message = MESSAGES[kind]
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
            archive.remove_partial(self.pipeline.workdir(job_id))
        lines = error_lines(detail, limit=1) or detail.strip().splitlines()[-1:]
        logger.warning("job %s %s: %s", job_id, kind, lines[0][:300] if lines else "")
