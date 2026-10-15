"""Orchestrate enqueue → download → sidecar/checksum → DB."""

from __future__ import annotations

import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lones_vdl import __version__
from lones_vdl.db import Database, JobRow, VideoRow, utc_now_iso
from lones_vdl.errors import (
    DuplicateArchiveError,
    LonesVdlError,
    PermanentDownloadError,
    TransientDownloadError,
)
from lones_vdl.platform.ytdlp import YtdlpAdapter, parse_youtube_id
from lones_vdl.storage import (
    PLATFORM_YOUTUBE,
    discard_partial,
    item_paths,
    prepare_partial_dir,
    promote_partial,
    relpath_under,
    write_checksums,
    write_sidecar,
)


def _source_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep a portable subset of yt-dlp metadata (not the entire blob)."""
    keys = (
        "id",
        "title",
        "fulltitle",
        "description",
        "channel",
        "channel_id",
        "uploader",
        "uploader_id",
        "upload_date",
        "release_timestamp",
        "timestamp",
        "duration",
        "width",
        "height",
        "fps",
        "ext",
        "format",
        "format_id",
        "vcodec",
        "acodec",
        "abr",
        "vbr",
        "tbr",
        "filesize_approx",
        "webpage_url",
        "original_url",
        "thumbnail",
        "tags",
        "categories",
        "chapters",
        "view_count",
        "like_count",
        "comment_count",
        "availability",
        "live_status",
        "was_live",
        "language",
        "subtitles",
        "automatic_captions",
    )
    return {key: raw[key] for key in keys if key in raw}


class ArchiveService:
    def __init__(
        self,
        *,
        db: Database,
        archive_root: Any,
        adapter: YtdlpAdapter,
        max_workers: int = 1,
        max_attempts: int = 3,
    ) -> None:
        self.db = db
        self.archive_root = archive_root
        self.adapter = adapter
        self.max_attempts = max_attempts
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="lones-dl")
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)

    def enqueue(
        self,
        url: str,
        *,
        quality_preference: str = "best",
        auto_start: bool = True,
    ) -> JobRow:
        hint_id = parse_youtube_id(url)
        if hint_id:
            existing = self.db.get_video(PLATFORM_YOUTUBE, hint_id)
            if existing is not None:
                raise DuplicateArchiveError(
                    f"Video {hint_id} is already archived",
                    platform_video_id=hint_id,
                )

        job = self.db.create_job(
            job_id=str(uuid.uuid4()),
            url=url,
            quality_preference=quality_preference,
            platform=PLATFORM_YOUTUBE,
            platform_video_id=hint_id,
        )
        if auto_start:
            self._executor.submit(self._process_job, job.id)
        return job

    def process_next_queued(self) -> JobRow | None:
        """Synchronously claim and process one queued job (tests / CLI)."""
        job = self.db.claim_next_queued_job()
        if job is None:
            return None
        return self._run_job(job)

    def _process_job(self, job_id: str) -> None:
        if self._closed:
            return
        with self._lock:
            job = self.db.get_job(job_id)
            if job is None or job.status != "queued":
                return
            job = self.db.update_job(job_id, status="downloading", attempts=job.attempts + 1)
        result = self._run_job(job)
        if result.status == "queued" and result.attempts < self.max_attempts and not self._closed:
            self._executor.submit(self._process_job, job_id)

    def _run_job(self, job: JobRow) -> JobRow:
        paths = None
        try:
            info = self.adapter.extract_info(job.url)
            existing = self.db.get_video(info.platform, info.video_id)
            if existing is not None:
                self.db.update_job(
                    job.id,
                    status="duplicate",
                    platform=info.platform,
                    platform_video_id=info.video_id,
                    video_id=existing.id,
                    error_code="duplicate",
                    error_message=f"Video {info.video_id} is already archived",
                )
                result = self.db.get_job(job.id)
                assert result is not None
                return result

            self.db.update_job(
                job.id,
                platform=info.platform,
                platform_video_id=info.video_id,
            )
            paths = item_paths(self.archive_root, info.platform, info.video_id)
            if paths.final_dir.exists() and any(paths.final_dir.glob("media.*")):
                # Files present but DB missing — treat as duplicate of on-disk archive.
                raise DuplicateArchiveError(
                    f"On-disk archive already exists for {info.video_id}",
                    platform_video_id=info.video_id,
                )

            prepare_partial_dir(paths)
            download = self.adapter.download(
                job.url,
                output_dir=paths.partial_dir,
                quality_preference=job.quality_preference,
            )

            # Organize thumbnails / subtitles inside partial before promote.
            thumb_dir = paths.partial_dir / "thumbnails"
            sub_dir = paths.partial_dir / "subtitles"
            if download.thumbnail_paths:
                thumb_dir.mkdir(exist_ok=True)
                for thumb in download.thumbnail_paths:
                    target = thumb_dir / thumb.name
                    if thumb.parent != thumb_dir:
                        shutil.move(str(thumb), target)
            if download.subtitle_paths:
                sub_dir.mkdir(exist_ok=True)
                for sub in download.subtitle_paths:
                    target = sub_dir / sub.name
                    if sub.parent != sub_dir:
                        shutil.move(str(sub), target)

            # Drop yt-dlp info json; we write our own sidecar after promote.
            for info_json in paths.partial_dir.glob("*.info.json"):
                info_json.unlink(missing_ok=True)

            promote_partial(paths)
            media_file = download.media_path
            # After promote, path root changed from .partial to final.
            media_file = paths.final_dir / media_file.name
            if not media_file.exists():
                raise PermanentDownloadError("media file missing after promote")

            checksum = write_checksums(paths, media_file)
            archived_at = utc_now_iso()
            write_sidecar(
                paths,
                source=_source_snapshot(download.info.raw),
                archive={
                    "downloaded_at": archived_at,
                    "job_id": job.id,
                    "quality_preference": job.quality_preference,
                    "original_url": job.url,
                    "tool_versions": {
                        "lones_vdl": __version__,
                        "yt-dlp": download.ytdlp_version,
                    },
                },
            )

            video = self.db.insert_video(
                platform=download.info.platform,
                platform_video_id=download.info.video_id,
                title=download.info.title,
                url=download.info.url,
                media_relpath=relpath_under(self.archive_root, media_file),
                metadata_relpath=relpath_under(self.archive_root, paths.metadata_path),
                checksum_sha256=checksum,
                archived_at=archived_at,
            )
            return self.db.update_job(
                job.id,
                status="completed",
                platform=video.platform,
                platform_video_id=video.platform_video_id,
                video_id=video.id,
                error_code=None,
                error_message=None,
            )
        except DuplicateArchiveError as exc:
            if paths is not None:
                discard_partial(paths)
            return self.db.update_job(
                job.id,
                status="duplicate",
                platform_video_id=exc.platform_video_id,
                error_code=exc.code,
                error_message=str(exc),
            )
        except TransientDownloadError as exc:
            if paths is not None:
                discard_partial(paths)
            attempts = job.attempts
            if attempts < self.max_attempts:
                return self.db.update_job(
                    job.id,
                    status="queued",
                    error_code=exc.code,
                    error_message=str(exc),
                )
            return self.db.update_job(
                job.id,
                status="failed",
                error_code=exc.code,
                error_message=str(exc),
            )
        except LonesVdlError as exc:
            if paths is not None:
                discard_partial(paths)
            return self.db.update_job(
                job.id,
                status="failed",
                error_code=exc.code,
                error_message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 — last-resort job failure boundary
            if paths is not None:
                discard_partial(paths)
            return self.db.update_job(
                job.id,
                status="failed",
                error_code="internal",
                error_message=str(exc),
            )

    def get_job(self, job_id: str) -> JobRow | None:
        return self.db.get_job(job_id)

    def list_jobs(self, *, limit: int = 50) -> list[JobRow]:
        return self.db.list_jobs(limit=limit)

    def list_videos(self, *, limit: int = 50) -> list[VideoRow]:
        return self.db.list_videos(limit=limit)

    def get_video(self, platform: str, platform_video_id: str) -> VideoRow | None:
        return self.db.get_video(platform, platform_video_id)
