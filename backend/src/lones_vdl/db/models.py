from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lones_vdl.db.base import Base, utcnow


class AppSetting(Base):
    """Small key/value store for runtime state (password hash, yt-dlp update info, ...)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # sha256 of the cookie token; the token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    remember: Mapped[bool] = mapped_column(default=False)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("platform", "channel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    channel_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(300))
    handle: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    videos: Mapped[list[Video]] = relationship(back_populates="channel")


class ContentKind(StrEnum):
    VIDEO = "video"
    SHORT = "short"
    STREAM = "stream"  # archived livestream / premiere VOD


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("platform", "video_id"),
        Index("ix_videos_upload_date", "upload_date"),
        Index("ix_videos_archived_at", "archived_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    video_id: Mapped[str] = mapped_column(String(100))
    content_kind: Mapped[str] = mapped_column(String(20), default=ContentKind.VIDEO)
    channel_pk: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    upload_date: Mapped[date | None]
    duration_seconds: Mapped[int | None]
    width: Mapped[int | None]
    height: Mapped[int | None]
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    source_url: Mapped[str] = mapped_column(String(500))
    # Paths relative to the archive root, POSIX style.
    directory: Mapped[str] = mapped_column(String(300))
    media_file: Mapped[str] = mapped_column(String(300))
    media_size: Mapped[int] = mapped_column(BigInteger)
    thumbnail_file: Mapped[str | None] = mapped_column(String(300))
    archived_at: Mapped[datetime] = mapped_column(default=utcnow)

    channel: Mapped[Channel | None] = relationship(back_populates="videos")


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


class JobStage(StrEnum):
    WAITING = "waiting"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    DONE = "done"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_next_attempt", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="download")
    url: Mapped[str] = mapped_column(String(500))
    platform: Mapped[str] = mapped_column(String(20))
    video_id: Mapped[str | None] = mapped_column(String(100), index=True)
    quality: Mapped[str] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    stage: Mapped[str] = mapped_column(String(20), default=JobStage.WAITING)
    progress: Mapped[float | None]  # 0..1 while downloading
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    next_attempt_at: Mapped[datetime] = mapped_column(default=utcnow)
    error_kind: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    ytdlp_version: Mapped[str | None] = mapped_column(String(40))
    video_pk: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
