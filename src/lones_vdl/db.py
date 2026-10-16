"""SQLite persistence for videos, jobs, and channel favorites."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

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
    channel TEXT,
    channel_id TEXT,
    upload_date TEXT,
    metadata_incomplete INTEGER NOT NULL DEFAULT 0,
    metadata_gaps TEXT,
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

CREATE TABLE IF NOT EXISTS channel_favorites (
    platform TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    channel TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (platform, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

# Created after column migration so existing DBs (pre-browse fields) can start.
_INDEXES_AFTER_MIGRATE = """
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(platform, channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_upload_date ON videos(upload_date);
CREATE INDEX IF NOT EXISTS idx_videos_title ON videos(title);
"""

_VIDEO_COLUMNS = {
    "channel": "TEXT",
    "channel_id": "TEXT",
    "upload_date": "TEXT",
    "metadata_incomplete": "INTEGER NOT NULL DEFAULT 0",
    "metadata_gaps": "TEXT",
}


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
    channel: str | None
    channel_id: str | None
    upload_date: str | None
    metadata_incomplete: bool
    metadata_gaps: tuple[str, ...]


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


@dataclass(frozen=True)
class ChannelRow:
    platform: str
    channel_id: str
    channel: str | None
    video_count: int
    favorited: bool


SortField = Literal["upload_date", "title", "archived_at"]
SortOrder = Literal["asc", "desc"]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.executescript(_INDEXES_AFTER_MIGRATE)
        self._conn.commit()

    def _migrate(self) -> None:
        existing = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(videos)").fetchall()
        }
        for column, decl in _VIDEO_COLUMNS.items():
            if column not in existing:
                self._conn.execute(f"ALTER TABLE videos ADD COLUMN {column} {decl}")

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

    def get_video_by_id(self, video_id: int) -> VideoRow | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
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
        channel: str | None = None,
        channel_id: str | None = None,
        upload_date: str | None = None,
        metadata_incomplete: bool = False,
        metadata_gaps: tuple[str, ...] | list[str] | None = None,
    ) -> VideoRow:
        archived = archived_at or utc_now_iso()
        gaps_json = json.dumps(list(metadata_gaps or []))
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO videos (
                    platform, platform_video_id, title, url,
                    media_relpath, metadata_relpath, checksum_sha256, archived_at,
                    channel, channel_id, upload_date, metadata_incomplete, metadata_gaps
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    channel,
                    channel_id,
                    upload_date,
                    1 if metadata_incomplete else 0,
                    gaps_json,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM videos WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
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

    def list_videos(
        self,
        *,
        limit: int = 50,
        q: str | None = None,
        channel_ids: list[str] | None = None,
        sort: SortField = "upload_date",
        order: SortOrder = "desc",
        incomplete_only: bool = False,
    ) -> list[VideoRow]:
        with self._lock:
            clauses: list[str] = []
            params: list[Any] = []
            if q:
                clauses.append(
                    "(title LIKE ? OR platform_video_id LIKE ? OR platform LIKE ?"
                    " OR url LIKE ? OR channel LIKE ? OR channel_id LIKE ?)"
                )
                needle = f"%{q}%"
                params.extend([needle] * 6)
            if channel_ids:
                placeholders = ",".join("?" for _ in channel_ids)
                clauses.append(f"channel_id IN ({placeholders})")
                params.extend(channel_ids)
            if incomplete_only:
                clauses.append("metadata_incomplete = 1")

            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            if sort == "title":
                order_sql = f"LOWER(COALESCE(title, platform_video_id)) {order.upper()}"
            elif sort == "archived_at":
                order_sql = f"archived_at {order.upper()}"
            else:
                # upload_date with archived_at fallback for sorting
                date_key = (
                    "COALESCE(upload_date, "
                    "substr(replace(replace(archived_at,'-',''),'T',''),1,8), "
                    "'00000000')"
                )
                order_sql = f"{date_key} {order.upper()}, archived_at {order.upper()}"
            query = f"SELECT * FROM videos{where} ORDER BY {order_sql} LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(query, params).fetchall()
            return [_video_from_row(r) for r in rows]

    def list_all_videos(self) -> list[VideoRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM videos ORDER BY platform, platform_video_id"
            ).fetchall()
            return [_video_from_row(r) for r in rows]

    def list_related(
        self,
        *,
        platform: str,
        channel_id: str | None,
        exclude_video_id: str,
        limit: int = 12,
    ) -> list[VideoRow]:
        if not channel_id:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM videos
                WHERE platform = ? AND channel_id = ? AND platform_video_id != ?
                ORDER BY COALESCE(
                    upload_date,
                    substr(replace(replace(archived_at,'-',''),'T',''),1,8),
                    '00000000'
                ) DESC
                LIMIT ?
                """,
                (platform, channel_id, exclude_video_id, limit),
            ).fetchall()
            return [_video_from_row(r) for r in rows]

    def list_channels(self, *, platform: str | None = None) -> list[ChannelRow]:
        with self._lock:
            params: list[Any] = []
            where = "WHERE v.channel_id IS NOT NULL"
            if platform:
                where += " AND v.platform = ?"
                params.append(platform)
            rows = self._conn.execute(
                f"""
                SELECT v.platform, v.channel_id,
                       MAX(v.channel) AS channel,
                       COUNT(*) AS video_count,
                       CASE WHEN f.channel_id IS NULL THEN 0 ELSE 1 END AS favorited
                FROM videos v
                LEFT JOIN channel_favorites f
                  ON f.platform = v.platform AND f.channel_id = v.channel_id
                {where}
                GROUP BY v.platform, v.channel_id
                ORDER BY favorited DESC, LOWER(COALESCE(MAX(v.channel), v.channel_id)) ASC
                """,
                params,
            ).fetchall()
            return [
                ChannelRow(
                    platform=r["platform"],
                    channel_id=r["channel_id"],
                    channel=r["channel"],
                    video_count=int(r["video_count"]),
                    favorited=bool(r["favorited"]),
                )
                for r in rows
            ]

    def set_channel_favorite(
        self,
        *,
        platform: str,
        channel_id: str,
        channel: str | None,
        favorited: bool,
    ) -> None:
        with self._lock:
            if favorited:
                self._conn.execute(
                    """
                    INSERT INTO channel_favorites (platform, channel_id, channel, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(platform, channel_id) DO UPDATE SET channel = excluded.channel
                    """,
                    (platform, channel_id, channel, utc_now_iso()),
                )
            else:
                self._conn.execute(
                    "DELETE FROM channel_favorites WHERE platform = ? AND channel_id = ?",
                    (platform, channel_id),
                )
            self._conn.commit()

    def upsert_video(
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
        channel: str | None = None,
        channel_id: str | None = None,
        upload_date: str | None = None,
        metadata_incomplete: bool = False,
        metadata_gaps: tuple[str, ...] | list[str] | None = None,
    ) -> tuple[VideoRow, str]:
        existing = self.get_video(platform, platform_video_id)
        if existing is None:
            return (
                self.insert_video(
                    platform=platform,
                    platform_video_id=platform_video_id,
                    title=title,
                    url=url,
                    media_relpath=media_relpath,
                    metadata_relpath=metadata_relpath,
                    checksum_sha256=checksum_sha256,
                    archived_at=archived_at,
                    channel=channel,
                    channel_id=channel_id,
                    upload_date=upload_date,
                    metadata_incomplete=metadata_incomplete,
                    metadata_gaps=metadata_gaps,
                ),
                "imported",
            )
        archived = archived_at or existing.archived_at
        gaps_json = json.dumps(list(metadata_gaps or []))
        with self._lock:
            self._conn.execute(
                """
                UPDATE videos
                SET title = ?, url = ?, media_relpath = ?, metadata_relpath = ?,
                    checksum_sha256 = ?, archived_at = ?,
                    channel = ?, channel_id = ?, upload_date = ?,
                    metadata_incomplete = ?, metadata_gaps = ?
                WHERE platform = ? AND platform_video_id = ?
                """,
                (
                    title,
                    url,
                    media_relpath,
                    metadata_relpath,
                    checksum_sha256,
                    archived,
                    channel,
                    channel_id,
                    upload_date,
                    1 if metadata_incomplete else 0,
                    gaps_json,
                    platform,
                    platform_video_id,
                ),
            )
            self._conn.commit()
        updated = self.get_video(platform, platform_video_id)
        assert updated is not None
        return updated, "updated"

    def delete_video(self, platform: str, platform_video_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM videos WHERE platform = ? AND platform_video_id = ?",
                (platform, platform_video_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

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


def _gaps_from_row(row: sqlite3.Row) -> tuple[str, ...]:
    raw = row["metadata_gaps"] if "metadata_gaps" in row.keys() else None
    if not raw:
        return ()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return tuple(str(x) for x in data)
    except json.JSONDecodeError:
        return ()
    return ()


def _video_from_row(row: sqlite3.Row) -> VideoRow:
    keys = row.keys()
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
        channel=row["channel"] if "channel" in keys else None,
        channel_id=row["channel_id"] if "channel_id" in keys else None,
        upload_date=row["upload_date"] if "upload_date" in keys else None,
        metadata_incomplete=bool(row["metadata_incomplete"])
        if "metadata_incomplete" in keys
        else False,
        metadata_gaps=_gaps_from_row(row),
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
