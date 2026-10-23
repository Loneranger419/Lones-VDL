"""Minimal video listing (Phase 2). Search, filters, and media streaming arrive in Phase 3."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lones_vdl.api.deps import AuthDep, DbDep
from lones_vdl.db.models import Video
from lones_vdl.schemas import VideoDetail, VideoOut

router = APIRouter(prefix="/videos", tags=["videos"], dependencies=[AuthDep])


@router.get("", response_model=list[VideoOut])
def list_videos(db: DbDep, limit: Annotated[int, Query(ge=1, le=500)] = 100):
    query = (
        select(Video)
        .options(selectinload(Video.channel))
        .order_by(Video.archived_at.desc())
        .limit(limit)
    )
    return db.scalars(query).all()


@router.get("/{video_pk}", response_model=VideoDetail)
def get_video(video_pk: int, db: DbDep):
    video = db.get(Video, video_pk, options=[selectinload(Video.channel)])
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "video not found")
    return video
