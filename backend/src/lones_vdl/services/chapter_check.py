"""Looking again for chapters or replay data of a recent video that lacks them.

Creators often add chapters, and YouTube adds "most replayed" once there are views. When such a
video is played, one small job asks the site for its metadata again and adds what is new to the
archived info.json. It follows the same download policy as subtitles: rate-limit pause,
anonymous first, alternate account at most, counted as a listing. When to ask is decided by
`chapters.check_due`.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import (
    ACTIVE_JOB_STATUSES,
    AttemptKind,
    Job,
    JobKind,
    JobStage,
    Video,
)
from lones_vdl.services import accounts as account_service
from lones_vdl.services import chapters as chapter_service
from lones_vdl.services.downloads import EnqueueError
from lones_vdl.services.jobs import PRIORITY_MANUAL, JobReporter, open_job_log
from lones_vdl.services.policy import Policy
from lones_vdl.storage import archive
from lones_vdl.ytdlp import CancelToken, ErrorKind, YtdlpError, YtdlpManager


def enqueue(db: DbSession, settings: Settings, video: Video) -> Job | None:
    """Queue a check if one is due; None when it is not (too soon, too old, has chapters)."""
    now = utcnow()
    current = chapter_service.load(settings, video)
    if not chapter_service.check_due(video, len(current.chapters), len(current.heatmap), now):
        return None
    active = db.scalars(
        select(Job).where(
            Job.kind == JobKind.CHAPTERS,
            Job.video_pk == video.id,
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
    ).first()
    if active is not None:
        raise EnqueueError(409, ErrorKind.CONFLICT, "Already queued.", job_id=active.id)
    # Marked now, not when it finishes: a paused or failing site is not asked again at once.
    video.chapters_checked_at = now
    job = Job(
        kind=JobKind.CHAPTERS,
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


class ChaptersPipeline:
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
            duration = float(video.duration_seconds) if video.duration_seconds else None
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
                    job.id, stage=JobStage.RESOLVING, ytdlp_version=self.ytdlp.version()
                )
                info, _ = runner.resolve(
                    job.url, quality="best", workdir=workdir, log=log, cancel=cancel
                )
            found = chapter_service.parse(info, duration)
            if found.chapters or found.heatmap:
                archive.update_chapter_data(item, info.get("chapters"), info.get("heatmap"))
            log.write(f"chapters: {len(found.chapters)}, replay data: {bool(found.heatmap)}\n")
        return {
            "video_pk": video.id,
            "result": {"chapters": len(found.chapters), "heatmap": bool(found.heatmap)},
        }
