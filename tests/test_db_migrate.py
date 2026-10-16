"""Migration must work on pre-browse-field SQLite databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from lones_vdl.db import Database


def test_opens_legacy_videos_table_without_channel_columns(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE videos (
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
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            platform TEXT,
            platform_video_id TEXT,
            quality_preference TEXT NOT NULL DEFAULT 'best',
            status TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT,
            video_id INTEGER,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO videos (
            platform, platform_video_id, title, url,
            media_relpath, metadata_relpath, checksum_sha256, archived_at
        ) VALUES (
            'youtube', 'legacyVid01', 'Legacy',
            'https://www.youtube.com/watch?v=legacyVid01',
            'youtube/legacyVid01/media.mkv',
            'youtube/legacyVid01/metadata.json',
            'abc', '2024-01-01T00:00:00+00:00'
        );
        """
    )
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        video = db.get_video("youtube", "legacyVid01")
        assert video is not None
        assert video.channel is None
        assert video.metadata_incomplete is False
        cols = {row["name"] for row in db._conn.execute("PRAGMA table_info(videos)").fetchall()}
        assert "channel_id" in cols
        assert "upload_date" in cols
    finally:
        db.close()
