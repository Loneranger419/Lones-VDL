"""SQLite persistence for videos, jobs, channels, and creator hubs."""

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
    content_kind TEXT NOT NULL DEFAULT 'video',
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

CREATE TABLE IF NOT EXISTS channel_watches (
    platform TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    channel TEXT,
    channel_url TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (platform, channel_id)
);

CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    avatar_platform TEXT,
    avatar_channel_id TEXT
);

CREATE TABLE IF NOT EXISTS creator_channels (
    creator_id INTEGER NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    PRIMARY KEY (platform, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_creator_channels_creator ON creator_channels(creator_id);
"""

_JOB_COLUMNS = {
    "watch_new": "INTEGER NOT NULL DEFAULT 0",
    "job_kind": "TEXT",
}

# Created after column migration so existing DBs (pre-browse fields) can start.
_INDEXES_AFTER_MIGRATE = """
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(platform, channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_upload_date ON videos(upload_date);
CREATE INDEX IF NOT EXISTS idx_videos_title ON videos(title);
CREATE INDEX IF NOT EXISTS idx_videos_content_kind ON videos(content_kind);
CREATE INDEX IF NOT EXISTS idx_videos_platform ON videos(platform);
"""

_VIDEO_COLUMNS = {
    "channel": "TEXT",
    "channel_id": "TEXT",
    "upload_date": "TEXT",
    "metadata_incomplete": "INTEGER NOT NULL DEFAULT 0",
    "metadata_gaps": "TEXT",
    "content_kind": "TEXT NOT NULL DEFAULT 'video'",
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
    content_kind: str = "video"


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
    watch_new: bool = False
    job_kind: str | None = None


@dataclass(frozen=True)
class ChannelRow:
    platform: str
    channel_id: str
    channel: str | None
    video_count: int
    favorited: bool
    watching: bool = False
    last_checked_at: str | None = None
    channel_url: str | None = None
    creator_id: int | None = None
    creator_name: str | None = None


@dataclass(frozen=True)
class ChannelWatchRow:
    platform: str
    channel_id: str
    channel: str | None
    channel_url: str | None
    enabled: bool
    last_checked_at: str | None
    created_at: str


@dataclass(frozen=True)
class CreatorRow:
    id: int
    display_name: str
    notes: str | None
    created_at: str
    avatar_platform: str | None = None
    avatar_channel_id: str | None = None


@dataclass(frozen=True)
class CreatorChannelRow:
    creator_id: int
    platform: str
    channel_id: str


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
        if "content_kind" not in existing:
            self._conn.execute(
                """
                UPDATE videos
                SET content_kind = 'video'
                WHERE content_kind IS NULL OR content_kind = ''
                """
            )
        job_cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()}
        for column, decl in _JOB_COLUMNS.items():
            if column not in job_cols:
                self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {decl}")
        # Ensure creator tables exist on DBs created before this feature.
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL,
                avatar_platform TEXT,
                avatar_channel_id TEXT
            );
            CREATE TABLE IF NOT EXISTS creator_channels (
                creator_id INTEGER NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                PRIMARY KEY (platform, channel_id)
            );
            CREATE INDEX IF NOT EXISTS idx_creator_channels_creator ON creator_channels(creator_id);
            """
        )
        creator_cols = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(creators)").fetchall()
        }
        if "avatar_platform" not in creator_cols:
            self._conn.execute("ALTER TABLE creators ADD COLUMN avatar_platform TEXT")
        if "avatar_channel_id" not in creator_cols:
            self._conn.execute("ALTER TABLE creators ADD COLUMN avatar_channel_id TEXT")

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
        content_kind: str = "video",
    ) -> VideoRow:
        archived = archived_at or utc_now_iso()
        gaps_json = json.dumps(list(metadata_gaps or []))
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO videos (
                    platform, platform_video_id, title, url,
                    media_relpath, metadata_relpath, checksum_sha256, archived_at,
                    channel, channel_id, upload_date, metadata_incomplete, metadata_gaps,
                    content_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    content_kind or "video",
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
        watch_new: bool = False,
        job_kind: str | None = None,
    ) -> JobRow:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    id, url, platform, platform_video_id, quality_preference,
                    status, created_at, updated_at, watch_new, job_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    url,
                    platform,
                    platform_video_id,
                    quality_preference,
                    status,
                    now,
                    now,
                    1 if watch_new else 0,
                    job_kind,
                ),
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
        channel_keys: list[tuple[str, str]] | None = None,
        platforms: list[str] | None = None,
        content_kinds: list[str] | None = None,
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
                    " OR url LIKE ? OR channel LIKE ? OR channel_id LIKE ?"
                    " OR content_kind LIKE ?)"
                )
                needle = f"%{q}%"
                params.extend([needle] * 7)
            if channel_keys:
                parts = []
                for platform, channel_id in channel_keys:
                    parts.append("(platform = ? AND channel_id = ?)")
                    params.extend([platform, channel_id])
                clauses.append(f"({' OR '.join(parts)})")
            if platforms:
                placeholders = ",".join("?" for _ in platforms)
                clauses.append(f"platform IN ({placeholders})")
                params.extend(platforms)
            if content_kinds:
                placeholders = ",".join("?" for _ in content_kinds)
                clauses.append(f"content_kind IN ({placeholders})")
                params.extend(content_kinds)
            if incomplete_only:
                clauses.append("metadata_incomplete = 1")

            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            if sort == "title":
                order_sql = f"LOWER(COALESCE(title, platform_video_id)) {order.upper()}"
            elif sort == "archived_at":
                order_sql = f"archived_at {order.upper()}"
            else:
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
        channel_keys = [(platform, channel_id)]
        creator = self.get_creator_for_channel(platform, channel_id)
        if creator is not None:
            linked = self.list_creator_channels(creator.id)
            if linked:
                channel_keys = [(c.platform, c.channel_id) for c in linked]
        with self._lock:
            parts: list[str] = []
            params: list[Any] = []
            for p, cid in channel_keys:
                parts.append("(platform = ? AND channel_id = ?)")
                params.extend([p, cid])
            params.extend([platform, exclude_video_id, platform, channel_id, limit])
            rows = self._conn.execute(
                f"""
                SELECT * FROM videos
                WHERE ({" OR ".join(parts)})
                  AND NOT (platform = ? AND platform_video_id = ?)
                ORDER BY
                  CASE WHEN platform = ? AND channel_id = ? THEN 0 ELSE 1 END,
                  COALESCE(
                      upload_date,
                      substr(replace(replace(archived_at,'-',''),'T',''),1,8),
                      '00000000'
                  ) DESC
                LIMIT ?
                """,
                params,
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
                       CASE WHEN f.channel_id IS NULL THEN 0 ELSE 1 END AS favorited,
                       CASE WHEN w.enabled = 1 THEN 1 ELSE 0 END AS watching,
                       w.last_checked_at AS last_checked_at,
                       w.channel_url AS channel_url,
                       cc.creator_id AS creator_id,
                       cr.display_name AS creator_name
                FROM videos v
                LEFT JOIN channel_favorites f
                  ON f.platform = v.platform AND f.channel_id = v.channel_id
                LEFT JOIN channel_watches w
                  ON w.platform = v.platform AND w.channel_id = v.channel_id
                LEFT JOIN creator_channels cc
                  ON cc.platform = v.platform AND cc.channel_id = v.channel_id
                LEFT JOIN creators cr ON cr.id = cc.creator_id
                {where}
                GROUP BY v.platform, v.channel_id
                ORDER BY watching DESC, favorited DESC,
                         LOWER(COALESCE(MAX(v.channel), v.channel_id)) ASC
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
                    watching=bool(r["watching"]),
                    last_checked_at=r["last_checked_at"],
                    channel_url=r["channel_url"],
                    creator_id=int(r["creator_id"]) if r["creator_id"] is not None else None,
                    creator_name=r["creator_name"],
                )
                for r in rows
            ]

    def set_channel_watch(
        self,
        *,
        platform: str,
        channel_id: str,
        channel: str | None,
        channel_url: str | None,
        watching: bool,
    ) -> None:
        with self._lock:
            if watching:
                self._conn.execute(
                    """
                    INSERT INTO channel_watches (
                        platform, channel_id, channel, channel_url, enabled, created_at
                    ) VALUES (?, ?, ?, ?, 1, ?)
                    ON CONFLICT(platform, channel_id) DO UPDATE SET
                        channel = COALESCE(excluded.channel, channel_watches.channel),
                        channel_url = COALESCE(excluded.channel_url, channel_watches.channel_url),
                        enabled = 1
                    """,
                    (platform, channel_id, channel, channel_url, utc_now_iso()),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE channel_watches SET enabled = 0
                    WHERE platform = ? AND channel_id = ?
                    """,
                    (platform, channel_id),
                )
                existing = self._conn.execute(
                    "SELECT 1 FROM channel_watches WHERE platform = ? AND channel_id = ?",
                    (platform, channel_id),
                ).fetchone()
                if existing is None:
                    self._conn.execute(
                        """
                        INSERT INTO channel_watches (
                            platform, channel_id, channel, channel_url, enabled, created_at
                        ) VALUES (?, ?, ?, ?, 0, ?)
                        """,
                        (platform, channel_id, channel, channel_url, utc_now_iso()),
                    )
            self._conn.commit()

    def list_enabled_watches(self) -> list[ChannelWatchRow]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM channel_watches
                WHERE enabled = 1
                ORDER BY LOWER(COALESCE(channel, channel_id)) ASC
                """
            ).fetchall()
            return [_watch_from_row(r) for r in rows]

    def touch_channel_watch(
        self,
        *,
        platform: str,
        channel_id: str,
        last_checked_at: str | None = None,
    ) -> None:
        checked = last_checked_at or utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE channel_watches
                SET last_checked_at = ?
                WHERE platform = ? AND channel_id = ?
                """,
                (checked, platform, channel_id),
            )
            self._conn.commit()

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

    def create_creator(self, *, display_name: str, notes: str | None = None) -> CreatorRow:
        now = utc_now_iso()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO creators (display_name, notes, created_at)
                VALUES (?, ?, ?)
                """,
                (display_name.strip(), notes, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM creators WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            assert row is not None
            return _creator_from_row(row)

    def get_creator(self, creator_id: int) -> CreatorRow | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM creators WHERE id = ?", (creator_id,)
            ).fetchone()
            return _creator_from_row(row) if row else None

    def list_creators(self) -> list[CreatorRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM creators ORDER BY LOWER(display_name) ASC"
            ).fetchall()
            return [_creator_from_row(r) for r in rows]

    def update_creator(
        self,
        creator_id: int,
        *,
        display_name: str | None = None,
        notes: str | None = None,
        avatar_platform: str | None = None,
        avatar_channel_id: str | None = None,
        clear_avatar: bool = False,
    ) -> CreatorRow | None:
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM creators WHERE id = ?", (creator_id,)
            ).fetchone()
            if existing is None:
                return None
            name = display_name.strip() if display_name is not None else existing["display_name"]
            note_val = notes if notes is not None else existing["notes"]
            keys = existing.keys()
            if clear_avatar:
                av_platform = None
                av_channel = None
            else:
                av_platform = (
                    avatar_platform
                    if avatar_platform is not None
                    else (existing["avatar_platform"] if "avatar_platform" in keys else None)
                )
                av_channel = (
                    avatar_channel_id
                    if avatar_channel_id is not None
                    else (existing["avatar_channel_id"] if "avatar_channel_id" in keys else None)
                )
            self._conn.execute(
                """
                UPDATE creators
                SET display_name = ?, notes = ?, avatar_platform = ?, avatar_channel_id = ?
                WHERE id = ?
                """,
                (name, note_val, av_platform, av_channel, creator_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM creators WHERE id = ?", (creator_id,)
            ).fetchone()
            assert row is not None
            return _creator_from_row(row)

    def delete_creator(self, creator_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM creators WHERE id = ?", (creator_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def list_creator_channels(self, creator_id: int) -> list[CreatorChannelRow]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM creator_channels
                WHERE creator_id = ?
                ORDER BY platform, channel_id
                """,
                (creator_id,),
            ).fetchall()
            return [
                CreatorChannelRow(
                    creator_id=int(r["creator_id"]),
                    platform=r["platform"],
                    channel_id=r["channel_id"],
                )
                for r in rows
            ]

    def get_creator_for_channel(self, platform: str, channel_id: str) -> CreatorRow | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT c.* FROM creators c
                JOIN creator_channels cc ON cc.creator_id = c.id
                WHERE cc.platform = ? AND cc.channel_id = ?
                """,
                (platform, channel_id),
            ).fetchone()
            return _creator_from_row(row) if row else None

    def attach_channel_to_creator(
        self,
        *,
        creator_id: int,
        platform: str,
        channel_id: str,
    ) -> None:
        with self._lock:
            if (
                self._conn.execute("SELECT 1 FROM creators WHERE id = ?", (creator_id,)).fetchone()
                is None
            ):
                raise ValueError(f"Creator {creator_id} not found")
            self._conn.execute(
                """
                INSERT INTO creator_channels (creator_id, platform, channel_id)
                VALUES (?, ?, ?)
                ON CONFLICT(platform, channel_id) DO UPDATE SET creator_id = excluded.creator_id
                """,
                (creator_id, platform, channel_id),
            )
            self._conn.commit()

    def detach_channel_from_creator(self, *, platform: str, channel_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM creator_channels WHERE platform = ? AND channel_id = ?",
                (platform, channel_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

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
        content_kind: str = "video",
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
                    content_kind=content_kind,
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
                    metadata_incomplete = ?, metadata_gaps = ?, content_kind = ?
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
                    content_kind or existing.content_kind or "video",
                    platform,
                    platform_video_id,
                ),
            )
            self._conn.commit()
        updated = self.get_video(platform, platform_video_id)
        assert updated is not None
        return updated, "updated"

    def clear_job_video_refs(self, video_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET video_id = NULL WHERE video_id = ?",
                (video_id,),
            )
            self._conn.commit()

    def has_active_job_for_video(self, platform: str, platform_video_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT 1 FROM jobs
                WHERE platform = ? AND platform_video_id = ?
                  AND status IN ('queued', 'downloading', 'expanding')
                LIMIT 1
                """,
                (platform, platform_video_id),
            ).fetchone()
            return row is not None

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
        content_kind=str(row["content_kind"])
        if "content_kind" in keys and row["content_kind"]
        else "video",
    )


def _job_from_row(row: sqlite3.Row) -> JobRow:
    keys = row.keys()
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
        watch_new=bool(row["watch_new"]) if "watch_new" in keys else False,
        job_kind=row["job_kind"] if "job_kind" in keys else None,
    )


def _watch_from_row(row: sqlite3.Row) -> ChannelWatchRow:
    return ChannelWatchRow(
        platform=row["platform"],
        channel_id=row["channel_id"],
        channel=row["channel"],
        channel_url=row["channel_url"],
        enabled=bool(row["enabled"]),
        last_checked_at=row["last_checked_at"],
        created_at=row["created_at"],
    )


def _creator_from_row(row: sqlite3.Row) -> CreatorRow:
    keys = row.keys()
    return CreatorRow(
        id=int(row["id"]),
        display_name=row["display_name"],
        notes=row["notes"],
        created_at=row["created_at"],
        avatar_platform=row["avatar_platform"] if "avatar_platform" in keys else None,
        avatar_channel_id=row["avatar_channel_id"] if "avatar_channel_id" in keys else None,
    )
