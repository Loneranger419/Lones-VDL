"""Orchestrate enqueue → download → sidecar/checksum → DB."""

from __future__ import annotations

import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lones_vdl import __version__
from lones_vdl.channel_avatars import channel_url_from_source, ensure_channel_avatar
from lones_vdl.db import ACTIVE_JOB_STATUSES, Database, JobRow, VideoRow, utc_now_iso
from lones_vdl.errors import (
    ConflictError,
    DuplicateArchiveError,
    LonesVdlError,
    PermanentDownloadError,
    TransientDownloadError,
)
from lones_vdl.metadata_fields import extract_browse_fields, source_snapshot
from lones_vdl.platform.url_router import classify_url, infer_content_kind, watch_fallback_url
from lones_vdl.platform.ytdlp import PlaylistListing, YtdlpAdapter
from lones_vdl.storage import (
    discard_partial,
    item_paths,
    prepare_partial_dir,
    promote_partial,
    relpath_under,
    write_checksums,
    write_sidecar,
)


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
        watch_new: bool = False,
    ) -> JobRow:
        classified = classify_url(url)
        if classified.kind == "video":
            if classified.hint_id:
                existing = self.db.get_video(classified.platform, classified.hint_id)
                if existing is not None:
                    raise DuplicateArchiveError(
                        f"Video {classified.hint_id} is already archived",
                        platform_video_id=classified.hint_id,
                    )
            job = self.db.create_job(
                job_id=str(uuid.uuid4()),
                url=url,
                quality_preference=quality_preference,
                platform=classified.platform,
                platform_video_id=classified.hint_id,
                job_kind="video",
            )
        else:
            job = self.db.create_job(
                job_id=str(uuid.uuid4()),
                url=url,
                quality_preference=quality_preference,
                platform=classified.platform,
                watch_new=watch_new and classified.kind == "channel",
                job_kind=classified.kind,
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

    def cancel_job(self, job_id: str, *, batch: bool = False) -> list[JobRow]:
        """Cancel an active job; with batch=True also cancel expand children."""
        job = self.db.get_job(job_id)
        if job is None:
            raise PermanentDownloadError(f"Job {job_id} not found", code="not_found")

        targets = [job_id]
        expand_kinds = {"playlist", "channel"}
        want_batch = batch or (job.job_kind in expand_kinds)
        if want_batch:
            targets.extend(child.id for child in self.db.list_child_jobs(job_id))
        # If this is a child, optional batch cancels siblings via parent.
        if batch and job.parent_job_id:
            parent_id = job.parent_job_id
            targets.append(parent_id)
            targets.extend(child.id for child in self.db.list_child_jobs(parent_id))

        # Dedupe preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for jid in targets:
            if jid not in seen:
                seen.add(jid)
                ordered.append(jid)

        cancelled_ids = self.db.cancel_jobs(ordered)
        if not cancelled_ids:
            if job.status not in ACTIVE_JOB_STATUSES:
                raise ConflictError(f"Job {job_id} is already {job.status}")
            raise ConflictError(f"No active jobs cancelled for {job_id}")
        return [j for jid in cancelled_ids if (j := self.db.get_job(jid)) is not None]

    def _is_cancelled(self, job_id: str) -> bool:
        row = self.db.get_job(job_id)
        return row is not None and row.status == "cancelled"

    def check_watched_channels(self) -> list[dict[str, Any]]:
        """Re-list enabled watches and enqueue any new uploads/VODs."""
        reports: list[dict[str, Any]] = []
        for watch in self.db.list_enabled_watches():
            url = watch_fallback_url(
                platform=watch.platform,
                channel_id=watch.channel_id,
                channel_url=watch.channel_url,
            )
            if not url:
                reports.append(
                    {
                        "platform": watch.platform,
                        "channel_id": watch.channel_id,
                        "status": "skipped",
                        "detail": "No channel_url stored",
                        "enqueued": 0,
                        "skipped": 0,
                    }
                )
                continue
            try:
                listing = self.adapter.list_entries(url)
                enqueued, skipped = self._fanout_listing(
                    listing,
                    quality_preference="best",
                    auto_start=True,
                    parent_job_id=None,
                )
                self.db.touch_channel_watch(
                    platform=watch.platform,
                    channel_id=watch.channel_id,
                )
                reports.append(
                    {
                        "platform": watch.platform,
                        "channel_id": watch.channel_id,
                        "status": "ok",
                        "detail": f"enqueued {enqueued}, skipped {skipped}",
                        "enqueued": enqueued,
                        "skipped": skipped,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — watch poll must not die
                reports.append(
                    {
                        "platform": watch.platform,
                        "channel_id": watch.channel_id,
                        "status": "failed",
                        "detail": str(exc),
                        "enqueued": 0,
                        "skipped": 0,
                    }
                )
        return reports

    def _process_job(self, job_id: str) -> None:
        if self._closed:
            return
        with self._lock:
            job = self.db.get_job(job_id)
            if job is None or job.status != "queued":
                return
            kind = job.job_kind
            if not kind:
                kind = classify_url(job.url).kind
            next_status = "expanding" if kind in {"playlist", "channel"} else "downloading"
            job = self.db.update_job(
                job_id,
                status=next_status,
                attempts=job.attempts + 1,
                job_kind=kind,
            )
        result = self._run_job(job)
        if result.status == "queued" and result.attempts < self.max_attempts and not self._closed:
            if not self._is_cancelled(job_id):
                self._executor.submit(self._process_job, job_id)

    def _fanout_listing(
        self,
        listing: PlaylistListing,
        *,
        quality_preference: str,
        auto_start: bool,
        parent_job_id: str | None = None,
    ) -> tuple[int, int]:
        enqueued = 0
        skipped = 0
        platform = listing.platform
        for entry in listing.entries:
            if parent_job_id and self._is_cancelled(parent_job_id):
                break
            existing = self.db.get_video(platform, entry.video_id)
            if existing is not None:
                skipped += 1
                continue
            paths = item_paths(self.archive_root, platform, entry.video_id)
            if paths.final_dir.exists() and any(paths.final_dir.glob("media.*")):
                skipped += 1
                continue
            child = self.db.create_job(
                job_id=str(uuid.uuid4()),
                url=entry.url,
                quality_preference=quality_preference,
                platform=platform,
                platform_video_id=entry.video_id,
                job_kind="video",
                parent_job_id=parent_job_id,
            )
            enqueued += 1
            if auto_start and not self._closed:
                self._executor.submit(self._process_job, child.id)
        return enqueued, skipped

    def _run_expand_job(self, job: JobRow) -> JobRow:
        if self._is_cancelled(job.id):
            result = self.db.get_job(job.id)
            assert result is not None
            return result
        listing = self.adapter.list_entries(job.url)
        if self._is_cancelled(job.id):
            result = self.db.get_job(job.id)
            assert result is not None
            return result
        platform = listing.platform
        if job.watch_new and listing.kind == "channel" and listing.channel_id:
            self.db.set_channel_watch(
                platform=platform,
                channel_id=listing.channel_id,
                channel=listing.channel,
                channel_url=listing.channel_url or listing.url,
                watching=True,
            )
            self.db.touch_channel_watch(
                platform=platform,
                channel_id=listing.channel_id,
            )
        enqueued, skipped = self._fanout_listing(
            listing,
            quality_preference=job.quality_preference,
            auto_start=True,
            parent_job_id=job.id,
        )
        if self._is_cancelled(job.id):
            result = self.db.get_job(job.id)
            assert result is not None
            return result
        summary = f"Expanded {listing.kind}: enqueued {enqueued}, skipped {skipped}"
        return self.db.update_job(
            job.id,
            status="completed",
            platform=platform,
            platform_video_id=listing.list_id or listing.channel_id,
            job_kind=listing.kind,
            error_code=None,
            error_message=summary,
        )

    def _run_job(self, job: JobRow) -> JobRow:
        if self._is_cancelled(job.id):
            result = self.db.get_job(job.id)
            assert result is not None
            return result
        kind = job.job_kind
        if not kind:
            kind = classify_url(job.url).kind
        if kind in {"playlist", "channel"}:
            try:
                return self._run_expand_job(job)
            except TransientDownloadError as exc:
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
                return self.db.update_job(
                    job.id,
                    status="failed",
                    error_code=exc.code,
                    error_message=str(exc),
                )
            except Exception as exc:  # noqa: BLE001
                return self.db.update_job(
                    job.id,
                    status="failed",
                    error_code="internal",
                    error_message=str(exc),
                )

        paths = None
        try:
            info = self.adapter.extract_info(job.url)
            if self._is_cancelled(job.id):
                result = self.db.get_job(job.id)
                assert result is not None
                return result
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
            if self._is_cancelled(job.id):
                discard_partial(paths)
                result = self.db.get_job(job.id)
                assert result is not None
                return result

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

            for info_json in paths.partial_dir.glob("*.info.json"):
                info_json.unlink(missing_ok=True)

            promote_partial(paths)
            media_file = download.media_path
            media_file = paths.final_dir / media_file.name
            if not media_file.exists():
                raise PermanentDownloadError("media file missing after promote")

            content_kind = infer_content_kind(
                platform=download.info.platform,
                url=job.url,
                raw=download.info.raw,
            )
            checksum = write_checksums(paths, media_file)
            archived_at = utc_now_iso()
            write_sidecar(
                paths,
                source=source_snapshot(download.info.raw),
                archive={
                    "downloaded_at": archived_at,
                    "job_id": job.id,
                    "quality_preference": job.quality_preference,
                    "original_url": job.url,
                    "content_kind": content_kind,
                    "tool_versions": {
                        "lones_vdl": __version__,
                        "yt-dlp": download.ytdlp_version,
                    },
                },
            )

            browse = extract_browse_fields(
                download.info.raw,
                fallback_url=download.info.url,
            )
            if browse.channel_id:
                ensure_channel_avatar(
                    archive_root=self.archive_root,
                    platform=download.info.platform,
                    channel_id=browse.channel_id,
                    channel_url=channel_url_from_source(download.info.raw),
                    adapter=self.adapter,
                )
            video = self.db.insert_video(
                platform=download.info.platform,
                platform_video_id=download.info.video_id,
                title=browse.title or download.info.title,
                url=browse.url or download.info.url,
                media_relpath=relpath_under(self.archive_root, media_file),
                metadata_relpath=relpath_under(self.archive_root, paths.metadata_path),
                checksum_sha256=checksum,
                archived_at=archived_at,
                channel=browse.channel,
                channel_id=browse.channel_id,
                upload_date=browse.upload_date,
                metadata_incomplete=browse.incomplete,
                metadata_gaps=browse.gaps,
                content_kind=content_kind,
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

    def list_videos(
        self,
        *,
        limit: int = 50,
        q: str | None = None,
        channel_keys: list[tuple[str, str]] | None = None,
        platforms: list[str] | None = None,
        content_kinds: list[str] | None = None,
        sort: str = "upload_date",
        order: str = "desc",
        incomplete_only: bool = False,
    ) -> list[VideoRow]:
        from lones_vdl.db import SortField, SortOrder

        allowed_sort = ("upload_date", "title", "archived_at")
        sort_field: SortField = sort if sort in allowed_sort else "upload_date"
        sort_order: SortOrder = order if order in ("asc", "desc") else "desc"
        return self.db.list_videos(
            limit=limit,
            q=q,
            channel_keys=channel_keys,
            platforms=platforms,
            content_kinds=content_kinds,
            sort=sort_field,
            order=sort_order,
            incomplete_only=incomplete_only,
        )

    def get_video(self, platform: str, platform_video_id: str) -> VideoRow | None:
        return self.db.get_video(platform, platform_video_id)

    def delete_video(self, platform: str, platform_video_id: str) -> VideoRow:
        """Remove DB row and on-disk item directory (final + partial)."""
        video = self.db.get_video(platform, platform_video_id)
        if video is None:
            raise PermanentDownloadError(
                f"Video {platform}/{platform_video_id} not found",
                code="not_found",
            )
        if self.db.has_active_job_for_video(platform, platform_video_id):
            raise ConflictError(
                f"Cannot delete {platform_video_id} while a job is queued or downloading"
            )
        paths = item_paths(self.archive_root, platform, platform_video_id)
        self.db.clear_job_video_refs(video.id)
        deleted = self.db.delete_video(platform, platform_video_id)
        if not deleted:
            raise PermanentDownloadError(
                f"Video {platform}/{platform_video_id} not found",
                code="not_found",
            )
        if paths.final_dir.exists():
            shutil.rmtree(paths.final_dir)
        if paths.partial_dir.exists():
            shutil.rmtree(paths.partial_dir)
        return video
