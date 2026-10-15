"""SQLite persistence for videos and download jobs."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    platform_video_id TEXT NOT NULL,
    title TEXT,
    url TEXT NOT NULL,
    media_relpath TEXT NOT NULL,
    metadata_relpath TEXT NOT NULL,
    checksum_sha256 TEXT,
    archived_at TEXT NOT NULL,
    UNIQUE (platform, platform_video_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    platform TEXT,
    platform_video_id TEXT,
    quality_preference TEXT NOT NULL DEFAULT 'best',
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    video_id INTEGER REFERENCES videos(id),
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class VideoRow:
    id: int
    platform: str
    platform_video_id: str
    title: str | None
    url: str
    media_relpath: str
    metadata_relpath: str
    checksum_sha256: str | None
    archived_at: str


@dataclass(frozen=True)
class JobRow:
    id: str
    url: str
    platform: str | None
    platform_video_id: str | None
    quality_preference: str
    status: str
    error_code: str | None
    error_message: str | None
    video_id: int | None
    attempts: int
    created_at: str
    updated_at: str


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_video(self, platform: str, platform_video_id: str) -> VideoRow | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM videos
                WHERE platform = ? AND platform_video_id = ?
                """,
                (platform, platform_video_id),
            ).fetchone()
            return _video_from_row(row) if row else None

    def insert_video(
        self,
        *,
        platform: str,
        platform_video_id: str,
        title: str | None,
        url: str,
        media_relpath: str,
        metadata_relpath: str,
        checksum_sha256: str | None,
        archived_at: str | None = None,
    ) -> VideoRow:
        archived = archived_at or utc_now_iso()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO videos (
                    platform, platform_video_id, title, url,
                    media_relpath, metadata_relpath, checksum_sha256, archived_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    platform_video_id,
                    title,
                    url,
                    media_relpath,
                    metadata_relpath,
                    checksum_sha256,
                    archived,
                ),
            )
            self._conn.commit()
            row_id = cur.lastrowid
            row = self._conn.execute("SELECT * FROM videos WHERE id = ?", (row_id,)).fetchone()
            assert row is not None
            return _video_from_row(row)

    def create_job(
        self,
        *,
        job_id: str,
        url: str,
        quality_preference: str,
        status: str = "queued",
        platform: str | None = None,
        platform_video_id: str | None = None,
    ) -> JobRow:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    id, url, platform, platform_video_id, quality_preference,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, url, platform, platform_video_id, quality_preference, status, now, now),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert row is not None
            return _job_from_row(row)

    def get_job(self, job_id: str) -> JobRow | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return _job_from_row(row) if row else None

    def list_jobs(self, *, limit: int = 50) -> list[JobRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [_job_from_row(r) for r in rows]

    def list_videos(self, *, limit: int = 50) -> list[VideoRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM videos ORDER BY archived_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [_video_from_row(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> JobRow:
        with self._lock:
            if not fields:
                row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                assert row is not None
                return _job_from_row(row)
            fields = {**fields, "updated_at": utc_now_iso()}
            assignments = ", ".join(f"{key} = ?" for key in fields)
            values = list(fields.values()) + [job_id]
            self._conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert row is not None
            return _job_from_row(row)

    def claim_next_queued_job(self) -> JobRow | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            job_id = row["id"]
            attempts = int(row["attempts"]) + 1
            now = utc_now_iso()
            self._conn.execute(
                """
                UPDATE jobs
                SET status = 'downloading', attempts = ?, updated_at = ?
                WHERE id = ?
                """,
                (attempts, now, job_id),
            )
            self._conn.commit()
            updated = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            assert updated is not None
            return _job_from_row(updated)


def _video_from_row(row: sqlite3.Row) -> VideoRow:
    return VideoRow(
        id=row["id"],
        platform=row["platform"],
        platform_video_id=row["platform_video_id"],
        title=row["title"],
        url=row["url"],
        media_relpath=row["media_relpath"],
        metadata_relpath=row["metadata_relpath"],
        checksum_sha256=row["checksum_sha256"],
        archived_at=row["archived_at"],
    )


def _job_from_row(row: sqlite3.Row) -> JobRow:
    return JobRow(
        id=row["id"],
        url=row["url"],
        platform=row["platform"],
        platform_video_id=row["platform_video_id"],
        quality_preference=row["quality_preference"],
        status=row["status"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        video_id=row["video_id"],
        attempts=row["attempts"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
