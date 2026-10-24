"""Pydantic models shared by the HTTP API and SSE events (one shape for both)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lones_vdl.ytdlp import QUALITIES


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- jobs -----------------------------------------------------------------------------


class JobOut(OrmModel):
    id: int
    kind: str
    url: str
    platform: str
    video_id: str | None
    quality: str
    title: str | None
    status: str
    stage: str
    progress: float | None
    priority: int
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    error_kind: str | None
    error_message: str | None
    ytdlp_version: str | None
    auth_tier: int
    approved_at: datetime | None
    content_kind: str | None
    options: dict[str, Any] | None
    result: dict[str, Any] | None
    parent_pk: int | None
    channel_pk: int | None
    video_pk: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class QueueSummary(BaseModel):
    """Waiting jobs by type (running ones are not counted)."""

    videos: int
    shorts: int
    streams: int
    listings: int  # playlist / channel checks
    subtitles: int


class JobProgress(BaseModel):
    """Lightweight high-frequency event; not persisted on every tick."""

    id: int
    stage: str
    progress: float | None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None


class EnqueueRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    quality: str | None = Field(default=None, description=f"one of {', '.join(QUALITIES)}")
    # Channel URLs only.
    watch: bool | None = Field(default=None, description="auto-archive new uploads")
    backfill: bool = Field(default=True, description="false: only uploads from now on")
    tabs: list[str] | None = Field(default=None, description="videos, streams, shorts")


class VerifyRequest(BaseModel):
    video_ids: list[int] | None = Field(default=None, description="omit to verify everything")


# --- channels / creators --------------------------------------------------------------


class ChannelOut(OrmModel):
    id: int
    platform: str
    channel_id: str
    name: str | None
    handle: str | None
    url: str | None
    has_avatar: bool


class ChannelDetail(ChannelOut):
    description: str | None
    has_banner: bool
    creator_pk: int | None
    watch_enabled: bool
    watch_videos: bool
    watch_streams: bool
    watch_shorts: bool
    watch_quality: str | None
    last_checked_at: datetime | None
    last_check_error: str | None
    created_at: datetime
    video_count: int = 0
    total_size: int = 0


class ChannelUpdate(BaseModel):
    watch_enabled: bool | None = None
    watch_videos: bool | None = None
    watch_streams: bool | None = None
    watch_shorts: bool | None = None
    watch_quality: str | None = None
    creator_id: int | None = None
    # When turning watch on: also download the existing back catalogue.
    backfill: bool = False


class CreatorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)
    channel_ids: list[int] = Field(default_factory=list)


class CreatorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)
    channel_ids: list[int] | None = None


class CreatorOut(OrmModel):
    id: int
    name: str
    notes: str | None
    created_at: datetime
    channels: list[ChannelOut]
    video_count: int = 0


# --- videos ---------------------------------------------------------------------------


class VideoOut(OrmModel):
    id: int
    platform: str
    video_id: str
    content_kind: str
    title: str
    upload_date: date | None
    duration_seconds: int | None
    width: int | None
    height: int | None
    media_size: int
    archived_at: datetime
    has_thumbnail: bool
    integrity: str
    position_seconds: float
    watched: bool
    last_watched_at: datetime | None
    channel: ChannelOut | None


class VideoDetail(VideoOut):
    description: str | None
    view_count: int | None
    like_count: int | None
    source_url: str
    directory: str
    media_file: str
    verified_at: datetime | None
    subtitles: list[str] = Field(default_factory=list, description="language codes")
    tags: list[str] = Field(default_factory=list)
    collection_ids: list[int] = Field(default_factory=list)


class VideoPage(BaseModel):
    items: list[VideoOut]
    total: int
    hidden: int = Field(0, description="matches hidden by the preset's tag rules")
    offset: int
    limit: int


class TagOut(BaseModel):
    tag: str = Field(description="lowercase key used in filters")
    label: str
    videos: int


class PresetOut(BaseModel):
    id: int
    name: str
    include: list[str]
    exclude: list[str]


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    include: list[str] = Field(default_factory=list, max_length=30, description="must have all")
    exclude: list[str] = Field(default_factory=list, max_length=60, description="must have none")


class PresetBookOut(BaseModel):
    presets: list[PresetOut]
    default_id: int | None


class DefaultPresetIn(BaseModel):
    preset_id: int | None


class RelatedOut(BaseModel):
    up_next: VideoOut | None
    more_from_channel: list[VideoOut]


class ProgressUpdate(BaseModel):
    position_seconds: float = Field(ge=0)


class WatchedUpdate(BaseModel):
    watched: bool


# --- collections ----------------------------------------------------------------------


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)


class CollectionOut(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    item_count: int
    cover_video_pk: int | None


class CollectionDetail(CollectionOut):
    videos: list[VideoOut]


class VideoIds(BaseModel):
    video_ids: list[int] = Field(max_length=5000)


# --- cookies / auth / system ----------------------------------------------------------


class CookieHealth(BaseModel):
    status: str  # ok | invalid | missing | untested | error
    checked_at: datetime
    detail: str | None = None


class CookieStatus(BaseModel):
    present: bool
    updated_at: datetime | None = None
    cookie_count: int = 0
    # Login cookie name -> expiry date ("session" for no expiry). Never values.
    login_cookies: dict[str, str] = Field(default_factory=dict)
    login_expires: str | None = None
    health: CookieHealth | None = None


class AccountOut(BaseModel):
    id: int
    label: str
    role: Literal["alternate", "personal"]
    enabled: bool
    created_at: datetime
    # Cookie state: names and expiry dates only, never values.
    status: CookieStatus


class AccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    role: Literal["alternate", "personal"]


class AccountUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None


class AccountImportOut(BaseModel):
    account: AccountOut
    summary: dict[str, Any]
    requeued_jobs: int


class RetryRequest(BaseModel):
    account_id: int | None = Field(
        default=None,
        description="run this job with this account (the personal one counts as approval)",
    )


class LimitGroup(BaseModel):
    """Use of one kind of content (videos, shorts, ...) over the last 24 hours."""

    key: str
    label: str
    used: int
    cap: int
    auth_used: int = Field(description="of `used`, how many used an account")
    auth_cap: int


class PlatformLimits(BaseModel):
    """One site's daily limits and pause. Each site has its own."""

    platform: str
    label: str
    groups: list[LimitGroup]
    paused_until: datetime | None
    pause_reason: str | None
    next_video_at: datetime | None
    # Last 7 days of attempts that started without an account.
    anonymous_ok_7d: int
    anonymous_refused_7d: int
    anonymous_other_7d: int


class PolicyStatus(BaseModel):
    """Use against the download policy's limits over the last 24 hours, per site."""

    platforms: list[PlatformLimits]


class CookieImportOut(BaseModel):
    status: CookieStatus
    summary: dict[str, Any]
    requeued_jobs: int


class AuthStatus(BaseModel):
    setup_required: bool
    authenticated: bool


class PasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = True


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class CheckOut(BaseModel):
    name: str
    status: str  # ok | warn | fail
    detail: str


class DoctorReport(BaseModel):
    ok: bool
    checks: list[CheckOut]


class YtdlpStatus(BaseModel):
    managed: bool
    installed: bool
    version: str | None
    channel: str
    updating: bool
    last_checked_at: datetime | None
    last_error: str | None


class StatsOut(BaseModel):
    videos: int
    total_bytes: int
    channels: int
    watched_channels: int
    creators: int
    collections: int
    by_kind: dict[str, int]
    by_integrity: dict[str, int]
    jobs: dict[str, int]
    archive_free_bytes: int | None
    archive_total_bytes: int | None
