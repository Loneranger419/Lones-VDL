"""Pydantic request/response models."""

from __future__ import annotations

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


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    platform_video_id: str | None = None
