"""Archive health: verify checksums, and rescan the archive to rebuild/repair the index."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import ACTIVE_JOB_STATUSES, Integrity, Job, JobKind, JobStage, Video
from lones_vdl.platforms import PLATFORMS, get_platform
from lones_vdl.schemas import JobProgress
from lones_vdl.services import channels as channel_service
from lones_vdl.services.downloads import index_video
from lones_vdl.services.jobs import JobReporter, open_job_log
from lones_vdl.storage import archive
from lones_vdl.ytdlp import Cancelled, CancelToken

logger = logging.getLogger(__name__)

HASH_CHUNK = 4 * 1024 * 1024


class MaintenanceBusy(Exception):
    def __init__(self, job: Job) -> None:
        super().__init__(f"a {job.kind} job is already active")
        self.job = job


def enqueue_maintenance(db: DbSession, kind: JobKind, *, video_ids: list[int] | None = None) -> Job:
    active = db.scalars(
        select(Job).where(Job.kind == kind, Job.status.in_(ACTIVE_JOB_STATUSES))
    ).first()
    if active is not None:
        raise MaintenanceBusy(active)
    title = "Verify checksums" if kind == JobKind.VERIFY else "Rescan archive"
    if video_ids is not None:
        title = f"{title} ({len(video_ids)} videos)"
    job = Job(
        kind=kind,
        url="",
        platform="",
        quality="",
        title=title,
        options={"video_ids": video_ids} if video_ids is not None else None,
        max_attempts=1,
    )
    db.add(job)
    db.flush()
    return job


def _sha256(path: Path, cancel: CancelToken) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(HASH_CHUNK):
            if cancel.cancelled:
                raise Cancelled()
            digest.update(block)
    return digest.hexdigest()


def verify_dir(path: Path, cancel: CancelToken) -> tuple[Integrity, str | None]:
    """Compare files against checksums.json. Returns (state, first problem)."""
    if not path.is_dir():
        return Integrity.MISSING, "directory missing"
    try:
        sums = json.loads((path / archive.CHECKSUMS_FILE).read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return Integrity.MISMATCH, f"checksums.json unreadable: {exc}"
    for rel, expected in sums.items():
        file = path / rel
        if not file.is_file():
            return Integrity.MISSING, f"{rel} missing"
        if _sha256(file, cancel) != expected:
            return Integrity.MISMATCH, f"{rel} checksum differs"
    return Integrity.OK, None


class VerifyPipeline:
    def __init__(self, settings: Settings, sessions: sessionmaker, reporter: JobReporter) -> None:
        self.settings = settings
        self.sessions = sessions
        self.reporter = reporter

    def cleanup(self, job_id: int) -> None:
        pass

    def run(self, job_id: int, cancel: CancelToken) -> dict[str, Any]:
        with self.sessions() as db:
            job = db.get_one(Job, job_id)
            query = select(Video.id, Video.directory).order_by(
                Video.verified_at.is_not(None), Video.verified_at, Video.id
            )
            wanted = (job.options or {}).get("video_ids")
            if wanted is not None:
                query = query.where(Video.id.in_(wanted))
            rows = db.execute(query).all()
        counts: Counter[str] = Counter()
        problems: list[str] = []
        with open_job_log(self.settings, job) as log:
            log.write(f"verifying {len(rows)} videos\n")
            for done, (pk, directory) in enumerate(rows):
                self.reporter.progress(
                    JobProgress(id=job_id, stage=JobStage.PROCESSING, progress=done / len(rows))
                )
                try:
                    path = archive.resolve_inside(self.settings.archive_root, directory)
                    state, problem = verify_dir(path, cancel)
                except ValueError as exc:
                    state, problem = Integrity.MISSING, str(exc)
                except OSError as exc:
                    state, problem = Integrity.MISMATCH, f"read error: {exc}"
                counts[state] += 1
                if problem:
                    log.write(f"{directory}: {state}: {problem}\n")
                    if len(problems) < 50:
                        problems.append(f"{directory}: {problem}")
                with self.sessions.begin() as db:
                    video = db.get(Video, pk)
                    if video is not None:
                        video.integrity = state
                        video.verified_at = utcnow()
            log.write(f"result: {dict(counts)}\n")
        return {"result": {"checked": len(rows), **counts, "problems": problems}}


class RescanPipeline:
    """Index archive items missing from the DB (e.g. after restoring a backup or losing the
    DB), flag DB rows whose files are gone, and drop leftover partial downloads."""

    def __init__(self, settings: Settings, sessions: sessionmaker, reporter: JobReporter) -> None:
        self.settings = settings
        self.sessions = sessions
        self.reporter = reporter

    def cleanup(self, job_id: int) -> None:
        pass

    def run(self, job_id: int, cancel: CancelToken) -> dict[str, Any]:
        root = self.settings.archive_root
        with self.sessions() as db:
            job = db.get_one(Job, job_id)
            unlinked = set(db.scalars(select(Video.directory).where(Video.channel_pk.is_(None))))
            indexed = set(db.scalars(select(Video.directory)))
        result: dict[str, Any] = {
            "scanned": 0,
            "indexed": 0,
            "relinked": 0,
            "missing": 0,
            "restored": 0,
        }
        errors: list[str] = []
        with open_job_log(self.settings, job) as log:
            dirs = [
                d
                for platform in PLATFORMS
                if (root / platform).is_dir()
                for d in sorted((root / platform).iterdir())
                if d.is_dir() and not d.name.startswith(("_", "."))
            ]
            seen: set[str] = set()
            for done, path in enumerate(dirs):
                if cancel.cancelled:
                    raise Cancelled()
                self.reporter.progress(
                    JobProgress(id=job_id, stage=JobStage.PROCESSING, progress=done / len(dirs))
                )
                rel = archive.relative(root, path)
                seen.add(rel)
                result["scanned"] += 1
                if rel in indexed:
                    if rel in unlinked and self._relink(path, rel):
                        result["relinked"] += 1
                    continue
                try:
                    if self._index(path, rel):
                        result["indexed"] += 1
                        log.write(f"indexed {rel}\n")
                except Exception as exc:  # noqa: BLE001 - one bad item must not stop the scan
                    log.write(f"skipped {rel}: {exc}\n")
                    if len(errors) < 50:
                        errors.append(f"{rel}: {exc}")
            missing, restored = self._flag_missing(seen)
            result["missing"], result["restored"] = missing, restored
            result["stale_partials_removed"] = self._remove_stale_partials()
            log.write(f"result: {result}\n")
        return {"result": {**result, "errors": errors}}

    def _relink(self, path: Path, rel: str) -> bool:
        """Restore a lost video -> channel link from the sidecar."""
        metadata_path = path / archive.METADATA_FILE
        if not metadata_path.is_file():
            return False
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        fields = metadata.get("channel") or {}
        with self.sessions.begin() as db:
            video = db.scalars(select(Video).where(Video.directory == rel)).first()
            if video is None:
                return False
            video.channel = channel_service.upsert_channel(db, video.platform, fields)
            return video.channel is not None

    def _index(self, path: Path, rel: str) -> bool:
        metadata_path = path / archive.METADATA_FILE
        if not metadata_path.is_file():
            return False
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        platform_name = metadata.get("platform") or path.parent.name
        video_id = metadata.get("video_id") or path.name
        info_path = path / archive.INFO_FILE
        info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}
        channel = metadata.get("channel") or {}
        # info.json wins; the sidecar fills gaps (e.g. info.json lost).
        info = {
            "id": video_id,
            "title": metadata.get("title"),
            "upload_date": metadata.get("upload_date"),
            "duration": metadata.get("duration_seconds"),
            "channel_id": channel.get("channel_id"),
            "channel": channel.get("name"),
            "uploader_id": channel.get("handle"),
            "channel_url": channel.get("url"),
            **{k: v for k, v in info.items() if v is not None},
        }
        files = metadata.get("files") or {}
        media = path / files["media"] if files.get("media") else None
        if media is None or not media.is_file():
            media = archive.discover_outputs(path).media
        thumbnail = files.get("thumbnail")
        archived_at = metadata.get("archived_at")
        with self.sessions.begin() as db:
            index_video(
                db,
                platform=platform_name,
                source_url=metadata.get("source_url")
                or get_platform(platform_name).video_url(video_id),
                info=info,
                directory=rel,
                media_file=media.name,
                media_size=media.stat().st_size,
                thumbnail_file=thumbnail if thumbnail and (path / thumbnail).is_file() else None,
                archived_at=datetime.fromisoformat(archived_at) if archived_at else None,
            )
        return True

    def _flag_missing(self, seen: set[str]) -> tuple[int, int]:
        missing = restored = 0
        with self.sessions.begin() as db:
            for video in db.scalars(select(Video)):
                present = video.directory in seen
                if not present and video.integrity != Integrity.MISSING:
                    video.integrity = Integrity.MISSING
                    missing += 1
                elif present and video.integrity == Integrity.MISSING:
                    video.integrity = Integrity.UNVERIFIED
                    restored += 1
        return missing, restored

    def _remove_stale_partials(self) -> int:
        partial = self.settings.partial_dir
        if not partial.is_dir():
            return 0
        with self.sessions() as db:
            active = {
                str(i)
                for i in db.scalars(
                    select(Job.id).where(
                        Job.kind == JobKind.DOWNLOAD, Job.status.in_(ACTIVE_JOB_STATUSES)
                    )
                )
            }
        removed = 0
        for path in partial.iterdir():
            if path.is_dir() and path.name not in active:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        return removed
