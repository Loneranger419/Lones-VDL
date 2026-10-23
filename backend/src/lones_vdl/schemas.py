"""Pydantic models shared by the HTTP API and SSE events (one shape for both)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from lones_vdl.ytdlp import QUALITIES


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    error_kind: str | None
    error_message: str | None
    ytdlp_version: str | None
    video_pk: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


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


class ChannelOut(OrmModel):
    id: int
    platform: str
    channel_id: str
    name: str | None
    handle: str | None
    url: str | None


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
    channel: ChannelOut | None


class VideoDetail(VideoOut):
    description: str | None
    view_count: int | None
    like_count: int | None
    source_url: str
    directory: str
    media_file: str
    thumbnail_file: str | None


class AuthStatus(BaseModel):
    setup_required: bool
    authenticated: bool


class PasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = True


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
