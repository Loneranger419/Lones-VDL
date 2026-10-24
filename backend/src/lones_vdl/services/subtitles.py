"""Fetching subtitles for an already archived video, on request.

Downloads skip subtitles because YouTube throttles that request on its own and a failure there
should never cost a video. This is a small job of its own: it follows the same download policy
(rate-limit pause, anonymous first, alternate account at most), and adds the captions to the
archived item without touching its media.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db.models import (
    ACTIVE_JOB_STATUSES,
    AttemptKind,
    Job,
    JobKind,
    JobStage,
    Video,
)
from lones_vdl.services import accounts as account_service
from lones_vdl.services import library
from lones_vdl.services.downloads import EnqueueError
from lones_vdl.services.jobs import PRIORITY_MANUAL, JobReporter, open_job_log
from lones_vdl.services.policy import Policy
from lones_vdl.storage import archive
from lones_vdl.ytdlp import CancelToken, ErrorKind, YtdlpError, YtdlpManager


def enqueue(db: DbSession, settings: Settings, video: Video) -> Job:
    if library.subtitle_langs(settings, video):
        raise EnqueueError(409, ErrorKind.CONFLICT, "This video already has subtitles.")
    active = db.scalars(
        select(Job).where(
            Job.kind == JobKind.SUBTITLES,
            Job.video_pk == video.id,
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
    ).first()
    if active is not None:
        raise EnqueueError(409, ErrorKind.CONFLICT, "Already queued.", job_id=active.id)
    job = Job(
        kind=JobKind.SUBTITLES,
        url=video.source_url,
        platform=video.platform,
        video_id=video.video_id,
        video_pk=video.id,
        quality="best",
        title=video.title,
        priority=PRIORITY_MANUAL,
        max_attempts=settings.download_max_attempts,
    )
    db.add(job)
    db.flush()
    return job


class SubtitlesPipeline:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker,
        ytdlp: YtdlpManager,
        reporter: JobReporter,
        policy: Policy,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.ytdlp = ytdlp
        self.reporter = reporter
        self.policy = policy

    def workdir(self, job_id: int) -> Path:
        return self.settings.data_dir / "tmp" / f"job-{job_id}"

    def cleanup(self, job_id: int) -> None:
        shutil.rmtree(self.workdir(job_id), ignore_errors=True)

    def run(self, job_id: int, cancel: CancelToken) -> dict[str, Any]:
        with self.sessions() as db:
            job = db.get_one(Job, job_id)
            video = db.get(Video, job.video_pk) if job.video_pk else None
            if video is None:
                raise YtdlpError(ErrorKind.UNAVAILABLE, "the video is no longer in the library")
            item = archive.resolve_inside(self.settings.archive_root, video.directory)
            # Like listings, this uses the alternate account at most, never the personal one.
            account = account_service.account_for_job(
                self.settings, db, job.auth_tier, (job.options or {}).get("account_id")
            )
            cookies_file = account_service.cookie_path(self.settings, account) if account else None
            label = account.label if account else None
        workdir = self.workdir(job.id)
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True)
        with (
            self.policy.attempt(job.id, account, AttemptKind.LISTING),
            open_job_log(self.settings, job) as log,
        ):
            log.write(f"access: {f'account {label!r}' if label else 'anonymous'}\n")
            with self.ytdlp.using(cookies_file) as runner:
                self.reporter.update(
                    job.id, stage=JobStage.DOWNLOADING, ytdlp_version=self.ytdlp.version()
                )
                runner.fetch_subtitles(job.url, workdir=workdir, log=log, cancel=cancel)
            found = sorted((workdir / "subtitles").glob("*.vtt"))
            if not found:
                raise YtdlpError(ErrorKind.NO_SUBTITLES)
            added = archive.add_subtitles(item, found)
            log.write(f"added {', '.join(added)}\n")
        return {"video_pk": video.id}
