from __future__ import annotations

from datetime import date, datetime
from enum import IntEnum, StrEnum
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, Text, UniqueConstraint
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


class Creator(Base):
    """A person/brand whose channels (possibly across platforms) are linked manually."""

    __tablename__ = "creators"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    channels: Mapped[list[Channel]] = relationship(back_populates="creator")


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("platform", "channel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    channel_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(300))
    handle: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    # Relative to the archive root, like Video paths.
    avatar_file: Mapped[str | None] = mapped_column(String(300))
    banner_file: Mapped[str | None] = mapped_column(String(300))
    creator_pk: Mapped[int | None] = mapped_column(
        ForeignKey("creators.id", ondelete="SET NULL"), index=True
    )
    # Auto-archive ("watch") settings.
    watch_enabled: Mapped[bool] = mapped_column(default=False)
    watch_videos: Mapped[bool] = mapped_column(default=True)
    watch_streams: Mapped[bool] = mapped_column(default=True)
    watch_shorts: Mapped[bool] = mapped_column(default=False)
    watch_quality: Mapped[str | None] = mapped_column(String(20))
    last_checked_at: Mapped[datetime | None]
    last_check_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    videos: Mapped[list[Video]] = relationship(back_populates="channel")
    creator: Mapped[Creator | None] = relationship(back_populates="channels")

    @property
    def has_avatar(self) -> bool:
        return self.avatar_file is not None

    @property
    def has_banner(self) -> bool:
        return self.banner_file is not None


class ContentKind(StrEnum):
    VIDEO = "video"
    SHORT = "short"
    STREAM = "stream"  # archived livestream / premiere VOD


class Integrity(StrEnum):
    UNVERIFIED = "unverified"
    OK = "ok"
    MISMATCH = "mismatch"  # checksum differs
    MISSING = "missing"  # files or directory gone


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
    integrity: Mapped[str] = mapped_column(String(20), default=Integrity.UNVERIFIED)
    verified_at: Mapped[datetime | None]

    channel: Mapped[Channel | None] = relationship(back_populates="videos")
    progress: Mapped[WatchProgress | None] = relationship(
        back_populates="video", cascade="all, delete-orphan", passive_deletes=True
    )

    # Flattened for API schemas; load with selectinload(Video.progress) to avoid N+1.
    @property
    def has_thumbnail(self) -> bool:
        return self.thumbnail_file is not None

    @property
    def position_seconds(self) -> float:
        return self.progress.position_seconds if self.progress else 0.0

    @property
    def watched(self) -> bool:
        return self.progress.watched if self.progress else False

    @property
    def last_watched_at(self) -> datetime | None:
        return self.progress.last_watched_at if self.progress else None


class WatchProgress(Base):
    """Single-user playback state. Not in sidecars: it is user data, not archive data."""

    __tablename__ = "watch_progress"
    __table_args__ = (Index("ix_watch_progress_last_watched_at", "last_watched_at"),)

    video_pk: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True
    )
    position_seconds: Mapped[float] = mapped_column(default=0.0)
    watched: Mapped[bool] = mapped_column(default=False)
    last_watched_at: Mapped[datetime] = mapped_column(default=utcnow)
    watched_at: Mapped[datetime | None]

    video: Mapped[Video] = relationship(back_populates="progress")


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    items: Mapped[list[CollectionItem]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="CollectionItem.position",
        passive_deletes=True,
    )


class CollectionItem(Base):
    __tablename__ = "collection_items"

    collection_pk: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    video_pk: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(default=0)
    added_at: Mapped[datetime] = mapped_column(default=utcnow)

    collection: Mapped[Collection] = relationship(back_populates="items")
    video: Mapped[Video] = relationship()


class IgnoredVideo(Base):
    """Ids that channel/playlist expansion must not queue (baseline, deleted, unavailable)."""

    __tablename__ = "ignored_videos"
    __table_args__ = (UniqueConstraint("platform", "video_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    video_id: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class JobKind(StrEnum):
    DOWNLOAD = "download"
    EXPAND = "expand"  # list a playlist/channel and queue what is new
    VERIFY = "verify"
    RESCAN = "rescan"
    SUBTITLES = "subtitles"  # fetch captions for an archived video, on request


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"  # needs the personal account; waits for the user
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.AWAITING_APPROVAL)


class AccountRole(StrEnum):
    ALTERNATE = "alternate"  # dedicated age-verified account, tried when anonymous is refused
    PERSONAL = "personal"  # only with explicit per-job approval


class AuthTier(IntEnum):
    """How much access a job may use. A job only moves up, one tier at a time."""

    ANONYMOUS = 0
    ALTERNATE = 1
    PERSONAL = 2


class AttemptKind(StrEnum):
    VIDEO = "video"
    LISTING = "listing"
    TEST = "test"


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
    kind: Mapped[str] = mapped_column(String(20), default=JobKind.DOWNLOAD)
    url: Mapped[str] = mapped_column(String(500))
    platform: Mapped[str] = mapped_column(String(20))
    video_id: Mapped[str | None] = mapped_column(String(100), index=True)
    quality: Mapped[str] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    stage: Mapped[str] = mapped_column(String(20), default=JobStage.WAITING)
    progress: Mapped[float | None]  # 0..1 while downloading
    # Higher runs first. Manual single videos > new uploads > backfill.
    priority: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    next_attempt_at: Mapped[datetime] = mapped_column(default=utcnow)
    error_kind: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    ytdlp_version: Mapped[str | None] = mapped_column(String(40))
    # Highest AuthTier the job may use next. Starts anonymous; see services/policy.
    auth_tier: Mapped[int] = mapped_column(default=AuthTier.ANONYMOUS, server_default="0")
    approved_at: Mapped[datetime | None]
    options: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    parent_pk: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    channel_pk: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    video_pk: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class Account(Base):
    """A signed-in identity whose cookies yt-dlp may use. Cookie values live in a 0600 file under
    secrets/accounts/, never in the database."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(100), unique=True)
    role: Mapped[str] = mapped_column(String(20), default=AccountRole.ALTERNATE)
    enabled: Mapped[bool] = mapped_column(default=True)
    health_status: Mapped[str | None] = mapped_column(String(20))
    health_checked_at: Mapped[datetime | None]
    health_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AccessAttempt(Base):
    """One request cycle to the platform. The source for daily caps, the gap between
    authenticated attempts, and anonymous success rates."""

    __tablename__ = "access_attempts"
    __table_args__ = (Index("ix_access_attempts_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_pk: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    # NULL = anonymous.
    account_pk: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), default=AttemptKind.VIDEO)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Set once the media download begins; only these count toward the daily caps.
    download_started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    # NULL while running; "ok", an ErrorKind value, or "interrupted" after a restart.
    outcome: Mapped[str | None] = mapped_column(String(30))
