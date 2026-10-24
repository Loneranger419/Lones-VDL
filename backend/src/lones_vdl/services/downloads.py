"""Enqueueing and the single-video download pipeline (resolve → download → promote → index)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any, TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl import __version__
from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import (
    AttemptKind,
    ContentKind,
    Job,
    JobKind,
    JobStage,
    JobStatus,
    Video,
)
from lones_vdl.platforms import UrlKind, parse_url
from lones_vdl.schemas import JobProgress
from lones_vdl.services import accounts as account_service
from lones_vdl.services import channels as channel_service
from lones_vdl.services.jobs import (
    PRIORITY_BACKFILL,
    PRIORITY_EXPAND,
    PRIORITY_MANUAL,
    PRIORITY_PLAYLIST,
    JobReporter,
    active_expand_for_url,
    active_job_for,
    open_job_log,
)
from lones_vdl.services.policy import AttemptHandle, Policy
from lones_vdl.storage import archive
from lones_vdl.ytdlp import QUALITIES, CancelToken, ErrorKind, YtdlpError, YtdlpManager
from lones_vdl.ytdlp.runner import parse_progress

logger = logging.getLogger(__name__)


class EnqueueError(Exception):
    def __init__(self, status: int, kind: ErrorKind, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.message = message
        self.extra = extra


def enqueue(
    db: DbSession,
    settings: Settings,
    url: str,
    quality: str | None,
    *,
    default_quality: str,
    watch: bool | None = None,
    backfill: bool = True,
    tabs: list[str] | None = None,
) -> Job:
    """Queue a video download, or an expansion job for a playlist/channel URL."""
    parsed = parse_url(url)
    if parsed is None:
        raise EnqueueError(422, ErrorKind.UNSUPPORTED, "Not a recognised YouTube URL.")
    explicit_quality = quality
    quality = quality or default_quality
    if quality not in QUALITIES:
        raise EnqueueError(422, ErrorKind.UNSUPPORTED, f"Unknown quality: {quality}")

    if parsed.kind == UrlKind.VIDEO:
        assert parsed.id is not None
        existing = db.scalars(
            select(Video).where(Video.platform == parsed.platform, Video.video_id == parsed.id)
        ).first()
        if existing is not None:
            raise EnqueueError(409, ErrorKind.CONFLICT, "Already archived.", video_pk=existing.id)
        active = active_job_for(db, parsed.platform, parsed.id)
        if active is not None:
            raise EnqueueError(409, ErrorKind.CONFLICT, "Already queued.", job_id=active.id)
        # An explicit request overrides an earlier "deleted"/"unavailable" ignore.
        channel_service.unignore(db, parsed.platform, parsed.id)
        job = Job(
            url=parsed.url,
            platform=parsed.platform,
            video_id=parsed.id,
            quality=quality,
            priority=PRIORITY_MANUAL,
            max_attempts=settings.download_max_attempts,
        )
    else:
        is_channel = parsed.kind == UrlKind.CHANNEL
        bad_tabs = set(tabs or []) - set(channel_service.TABS)
        if bad_tabs:
            raise EnqueueError(422, ErrorKind.UNSUPPORTED, f"Unknown tabs: {sorted(bad_tabs)}")
        options: dict[str, Any] = {
            "mode": "all" if backfill or not is_channel else "baseline",
            "quality": quality,
            "child_priority": PRIORITY_BACKFILL if is_channel else PRIORITY_PLAYLIST,
        }
        if is_channel:
            options["tabs"] = tabs or ["videos", "streams"]
            if watch is not None:
                options["watch"] = watch
                # Pin the channel's quality only when chosen; otherwise it follows the default.
                options["watch_quality"] = explicit_quality
        active = active_expand_for_url(db, parsed.url)
        if active is not None:
            meta_only = (active.options or {}).get("mode") == "meta"
            if not (meta_only and active.status == JobStatus.QUEUED):
                raise EnqueueError(
                    409, ErrorKind.CONFLICT, "Already being listed.", job_id=active.id
                )
            # A queued background metadata refresh: turn it into the full listing.
            active.options = options
            active.quality = quality
            active.priority = PRIORITY_EXPAND
            active.max_attempts = settings.download_max_attempts
            active.next_attempt_at = utcnow()
            db.flush()
            return active
        job = Job(
            kind=JobKind.EXPAND,
            url=parsed.url,
            platform=parsed.platform,
            quality=quality,
            priority=PRIORITY_EXPAND,
            options=options,
            max_attempts=settings.download_max_attempts,
        )
    db.add(job)
    db.flush()
    return job


class ProgressTracker:
    """Turn yt-dlp output lines into overall progress across video+audio downloads."""

    _PROCESSING_MARKERS = ("[Merger]", "[FixupM", "[VideoConvertor]", "[ExtractAudio]")

    def __init__(
        self, job_id: int, expected_total: int | None, report: Callable[[JobProgress], None]
    ) -> None:
        self.job_id = job_id
        self.expected_total = expected_total
        self.report = report
        self._formats: dict[str, tuple[int, int]] = {}

    def feed(self, line: str) -> None:
        if line.startswith(self._PROCESSING_MARKERS):
            self.report(JobProgress(id=self.job_id, stage=JobStage.PROCESSING, progress=1.0))
            return
        progress = parse_progress(line)
        if progress is None or progress.downloaded_bytes is None:
            return
        done = progress.downloaded_bytes
        self._formats[progress.format_id or "?"] = (done, progress.total_bytes or done)
        downloaded = sum(d for d, _ in self._formats.values())
        total = max(self.expected_total or 0, sum(t for _, t in self._formats.values()))
        self.report(
            JobProgress(
                id=self.job_id,
                stage=JobStage.DOWNLOADING,
                progress=min(downloaded / total, 1.0) if total else None,
                downloaded_bytes=downloaded,
                total_bytes=total or None,
                speed=progress.speed,
                eta=progress.eta,
            )
        )


def expected_size(info: dict[str, Any]) -> int | None:
    formats = info.get("requested_formats") or [info]
    sizes = [f.get("filesize") or f.get("filesize_approx") for f in formats]
    return int(sum(sizes)) if sizes and all(sizes) else None


def content_kind(info: dict[str, Any]) -> ContentKind:
    if info.get("was_live") or info.get("live_status") in {"was_live", "post_live"}:
        return ContentKind.STREAM
    width, height, duration = info.get("width"), info.get("height"), info.get("duration")
    if width and height and height > width and duration and duration <= 180:
        return ContentKind.SHORT
    return ContentKind.VIDEO


def parse_upload_date(value: Any) -> date | None:
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def build_metadata(
    *,
    job: Job,
    info: dict[str, Any],
    outputs: archive.Outputs,
    workdir: Path,
    ytdlp_version: str | None,
) -> dict[str, Any]:
    def rel(path: Path | None) -> str | None:
        return path.relative_to(workdir).as_posix() if path else None

    return {
        "platform": job.platform,
        "video_id": info["id"],
        "content_kind": content_kind(info).value,
        "title": info.get("title"),
        "channel": channel_service.channel_fields(info),
        "upload_date": info.get("upload_date"),
        "duration_seconds": info.get("duration"),
        "source_url": job.url,
        "archived_at": utcnow().isoformat(),
        "archived_by": {"app_version": __version__, "ytdlp_version": ytdlp_version},
        "quality": job.quality,
        "format": {
            key: info.get(key)
            for key in ("format_id", "ext", "width", "height", "fps", "vcodec", "acodec")
        },
        "files": {
            "media": rel(outputs.media),
            "info": rel(outputs.info),
            "thumbnail": rel(outputs.thumbnail),
            "subtitles": [rel(s) for s in outputs.subtitles],
        },
    }


def index_video(
    db: DbSession,
    *,
    platform: str,
    source_url: str,
    info: dict[str, Any],
    directory: str,
    media_file: str,
    media_size: int,
    thumbnail_file: str | None,
    archived_at: datetime | None = None,
) -> Video:
    """Insert the DB row for an archived item (also used by rescan)."""
    channel = channel_service.upsert_channel(db, platform, channel_service.channel_fields(info))
    video = Video(
        platform=platform,
        video_id=info["id"],
        content_kind=content_kind(info),
        channel=channel,
        title=info.get("title") or info["id"],
        description=info.get("description"),
        upload_date=parse_upload_date(info.get("upload_date")),
        duration_seconds=int(info["duration"]) if info.get("duration") else None,
        width=info.get("width"),
        height=info.get("height"),
        view_count=info.get("view_count"),
        like_count=info.get("like_count"),
        source_url=source_url,
        directory=directory,
        media_file=media_file,
        media_size=media_size,
        thumbnail_file=thumbnail_file,
        archived_at=archived_at or utcnow(),
    )
    db.add(video)
    db.flush()
    return video


class DownloadPipeline:
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

    def cleanup(self, job_id: int) -> None:
        archive.remove_partial(self.settings.partial_dir / str(job_id))

    def run(self, job_id: int, cancel: CancelToken) -> dict[str, Any]:
        """Run one attempt. Returns fields to set on the completed job; raises on failure."""
        with self.sessions() as db:
            job = db.get_one(Job, job_id)
            account = account_service.account_for_job(
                self.settings, db, job.auth_tier, (job.options or {}).get("account_id")
            )
            cookies_file = account_service.cookie_path(self.settings, account) if account else None
            label = account.label if account else None
        with (
            self.policy.attempt(job.id, account, AttemptKind.VIDEO) as attempt,
            open_job_log(self.settings, job) as log,
        ):
            log.write(f"access: {f'account {label!r}' if label else 'anonymous'}\n")
            video_pk = self._run(job, cancel, log, cookies_file, attempt)
        return {"video_pk": video_pk}

    def _run(
        self,
        job: Job,
        cancel: CancelToken,
        log: TextIO,
        cookies_file: Path | None,
        attempt: AttemptHandle,
    ) -> int:
        workdir = archive.partial_dir(self.settings.partial_dir, job.id)
        with self.ytdlp.using(cookies_file) as runner:
            version = self.ytdlp.version()
            self.reporter.update(job.id, stage=JobStage.RESOLVING, ytdlp_version=version)
            log.write(f"yt-dlp {version} cookies={'yes' if runner.has_cookies else 'no'}\n")
            info, info_path = runner.resolve(
                job.url, quality=job.quality, workdir=workdir, log=log, cancel=cancel
            )
            video_id = str(info["id"])
            self.reporter.update(job.id, video_id=video_id, title=info.get("title"))
            dest = archive.video_dir(self.settings.archive_root, job.platform, video_id)
            self._check_conflict(job, video_id, dest)

            attempt.download_started()
            tracker = ProgressTracker(job.id, expected_size(info), self.reporter.progress)
            self.reporter.progress(
                JobProgress(id=job.id, stage=JobStage.DOWNLOADING, progress=0.0), force=True
            )
            runner.download(
                info_path,
                quality=job.quality,
                workdir=workdir,
                log=log,
                on_line=tracker.feed,
                cancel=cancel,
            )

        self.reporter.progress(
            JobProgress(id=job.id, stage=JobStage.PROCESSING, progress=None), force=True
        )
        outputs = archive.normalize(
            workdir, archive.discover_outputs(workdir), fallback_info=info_path
        )
        if outputs.info is not None:
            info = json.loads(outputs.info.read_text(encoding="utf-8"))
        archive.write_sidecar(
            workdir,
            build_metadata(
                job=job, info=info, outputs=outputs, workdir=workdir, ytdlp_version=version
            ),
        )
        archive.write_checksums(workdir)
        media_size = outputs.media.stat().st_size
        self._check_conflict(job, video_id, dest)
        archive.promote(workdir, dest)
        log.write(f"archived to {dest}\n")

        with self.sessions.begin() as db:
            video = index_video(
                db,
                platform=job.platform,
                source_url=job.url,
                info=info,
                directory=archive.relative(self.settings.archive_root, dest),
                media_file=outputs.media.name,
                media_size=media_size,
                thumbnail_file=outputs.thumbnail.name if outputs.thumbnail else None,
            )
            self._queue_channel_metadata(db, video)
            return video.id

    def _queue_channel_metadata(self, db: DbSession, video: Video) -> None:
        """First video from a channel: fetch its avatar/banner/description in the background."""
        channel = video.channel
        if channel is None or channel.last_checked_at is not None or channel.avatar_file:
            return
        if channel_service.active_expand_for_channel(db, channel.id) is not None:
            return
        db.add(
            Job(
                kind=JobKind.EXPAND,
                url=channel_service.channel_base_url(channel),
                platform=channel.platform,
                quality="best",
                priority=PRIORITY_EXPAND,
                channel_pk=channel.id,
                title=channel.name,
                options={"mode": "meta", "tabs": ["videos"], "limit": 1},
                max_attempts=1,
            )
        )

    def _check_conflict(self, job: Job, video_id: str, dest: Path) -> None:
        with self.sessions() as db:
            exists = db.scalars(
                select(Video.id).where(Video.platform == job.platform, Video.video_id == video_id)
            ).first()
        if exists is not None:
            raise YtdlpError(ErrorKind.CONFLICT, f"video {video_id} is already archived")
        if dest.exists():
            raise YtdlpError(
                ErrorKind.CONFLICT, f"{dest} exists on disk but is not indexed; run a rescan"
            )
