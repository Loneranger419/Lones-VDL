"""Pydantic request/response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EnqueueRequest(BaseModel):
    url: str = Field(
        ...,
        min_length=8,
        description="YouTube or Twitch video/VOD/clip, playlist, or channel URL",
    )
    quality_preference: str = Field(default="best", min_length=1)
    watch_new: bool = Field(
        default=False,
        description="When enqueueing a channel URL, enable watch-for-new uploads/VODs",
    )


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
    watch_new: bool = False
    job_kind: str | None = None


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
    content_kind: str = "video"


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
    has_thumbnail: bool = False
    watching: bool = False
    last_checked_at: str | None = None
    channel_url: str | None = None
    creator_id: int | None = None
    creator_name: str | None = None


class FavoriteRequest(BaseModel):
    favorited: bool = True
    channel: str | None = None


class WatchRequest(BaseModel):
    watching: bool = True
    channel: str | None = None
    channel_url: str | None = None


class WatchCheckItem(BaseModel):
    platform: str
    channel_id: str
    status: str
    detail: str
    enqueued: int
    skipped: int


class CreatorChannelRef(BaseModel):
    platform: str
    channel_id: str
    channel: str | None = None
    has_thumbnail: bool = False


class CreatorResponse(BaseModel):
    id: int
    display_name: str
    notes: str | None = None
    created_at: str
    channels: list[CreatorChannelRef] = Field(default_factory=list)
    avatar_platform: str | None = None
    avatar_channel_id: str | None = None
    has_thumbnail: bool = False


class CreatorCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=200)
    notes: str | None = None


class CreatorUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    avatar_platform: str | None = None
    avatar_channel_id: str | None = None
    clear_avatar: bool = False


class CreatorAttachRequest(BaseModel):
    platform: str = Field(..., min_length=1)
    channel_id: str = Field(..., min_length=1)


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
