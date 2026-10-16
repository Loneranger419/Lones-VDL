"""Pydantic request/response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EnqueueRequest(BaseModel):
    url: str = Field(..., min_length=8, description="YouTube video URL")
    quality_preference: str = Field(default="best", min_length=1)


class JobResponse(BaseModel):
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


class VideoResponse(BaseModel):
    id: int
    platform: str
    platform_video_id: str
    title: str | None
    url: str
    media_relpath: str
    metadata_relpath: str
    checksum_sha256: str | None
    archived_at: str
    has_thumbnail: bool = False
    channel: str | None = None
    channel_id: str | None = None
    upload_date: str | None = None
    metadata_incomplete: bool = False
    metadata_gaps: list[str] = Field(default_factory=list)


class PlaybackInfo(BaseModel):
    mode: Literal["original", "remux", "unavailable"]
    container: str | None
    reason: str
    video_codec: str | None
    audio_codec: str | None
    play_path: str | None = None
    original_path: str | None = None


class VideoDetailResponse(VideoResponse):
    source_metadata: dict[str, Any] | None = None
    archive_metadata: dict[str, Any] | None = None
    playback: PlaybackInfo | None = None


class ChannelResponse(BaseModel):
    platform: str
    channel_id: str
    channel: str | None
    video_count: int
    favorited: bool


class FavoriteRequest(BaseModel):
    favorited: bool = True
    channel: str | None = None


class RefreshResultResponse(BaseModel):
    platform: str
    platform_video_id: str
    status: str
    detail: str
    gaps: list[str]


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    platform_video_id: str | None = None


class PublicConfigResponse(BaseModel):
    """Non-secret operator settings for the web UI."""

    default_quality: str
    archive_root: str
    download_concurrency: int
    download_max_attempts: int
    cookies_configured: bool
    cookie_platforms: list[str]
    cookie_count: int | None = None
    quality_presets: list[str]


class CookieFilterResponse(BaseModel):
    platforms: list[str]
    domains_allowed: list[str]
    cookies_before: int
    cookies_after: int
    cookies_removed: int
    lines_before: int
    lines_after: int
    backup_path: str | None = None


class VerifyItemResponse(BaseModel):
    platform: str
    platform_video_id: str
    status: str
    detail: str
    expected_sha256: str | None = None
    actual_sha256: str | None = None


class VerifyReportResponse(BaseModel):
    checked: int
    ok: int
    issue_count: int
    issues: list[VerifyItemResponse]


class RescanItemResponse(BaseModel):
    platform: str
    platform_video_id: str
    action: str
    detail: str


class RescanReportResponse(BaseModel):
    scanned: int
    imported: int
    updated: int
    skipped: int
    errors: int
    missing_from_disk: list[str]
    items: list[RescanItemResponse]
