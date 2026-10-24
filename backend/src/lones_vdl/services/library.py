"""Browsing the archive: search/filter/sort, related videos, watch progress, deletion, stats."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import selectinload

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import (
    Channel,
    Collection,
    CollectionItem,
    Creator,
    Job,
    Video,
    WatchProgress,
)
from lones_vdl.services import channels as channel_service
from lones_vdl.services import tags as tag_service
from lones_vdl.storage import archive

# Playback past this fraction of the duration marks a video watched.
WATCHED_FRACTION = 0.9

Sort = Literal[
    "archived_desc",
    "archived_asc",
    "uploaded_desc",
    "uploaded_asc",
    "title",
    "duration_desc",
    "duration_asc",
    "watched_desc",
]
WatchFilter = Literal["unwatched", "in_progress", "watched"]

_ORDER = {
    "archived_desc": (Video.archived_at.desc(),),
    "archived_asc": (Video.archived_at.asc(),),
    "uploaded_desc": (Video.upload_date.desc().nulls_last(), Video.archived_at.desc()),
    "uploaded_asc": (Video.upload_date.asc().nulls_last(), Video.archived_at.asc()),
    "title": (func.lower(Video.title),),
    "duration_desc": (Video.duration_seconds.desc().nulls_last(),),
    "duration_asc": (Video.duration_seconds.asc().nulls_last(),),
    "watched_desc": (WatchProgress.last_watched_at.desc().nulls_last(),),
}


def with_relations(query: Select) -> Select:
    return query.options(selectinload(Video.channel), selectinload(Video.progress))


@dataclass
class VideoQuery:
    q: str | None = None
    channel_pk: int | None = None
    creator_pk: int | None = None
    kind: str | None = None
    watch: WatchFilter | None = None
    integrity: str | None = None
    tags: list[str] = field(default_factory=list)  # has all of these
    exclude_tags: list[str] = field(default_factory=list)  # has none of these
    # A preset's rules, kept apart so the number of videos it hides can be counted.
    preset_tags: list[str] = field(default_factory=list)
    preset_exclude_tags: list[str] = field(default_factory=list)
    sort: Sort = "archived_desc"
    offset: int = 0
    limit: int = 48


def query_videos(db: DbSession, params: VideoQuery) -> tuple[list[Video], int, int]:
    """(page of videos, total matching, how many more the preset rules hide)."""
    query = _filtered(params)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    hidden = 0
    if tag_service.has_filter(params.preset_tags, params.preset_exclude_tags):
        unfiltered = db.scalar(
            select(func.count()).select_from(_filtered(params, use_preset=False).subquery())
        )
        hidden = max((unfiltered or 0) - total, 0)
    items = db.scalars(
        with_relations(query)
        .order_by(*_ORDER[params.sort], Video.id.desc())
        .offset(params.offset)
        .limit(params.limit)
    ).all()
    return list(items), total, hidden


def _filtered(params: VideoQuery, *, use_preset: bool = True) -> Select:
    query = select(Video).outerjoin(WatchProgress, WatchProgress.video_pk == Video.id)
    if params.q:
        query = query.outerjoin(Channel, Channel.id == Video.channel_pk)
        for word in params.q.split()[:10]:
            pattern = f"%{_escape_like(word)}%"
            query = query.where(
                or_(
                    Video.title.ilike(pattern, escape="\\"),
                    Channel.name.ilike(pattern, escape="\\"),
                    Video.video_id == word,
                )
            )
    if params.channel_pk is not None:
        query = query.where(Video.channel_pk == params.channel_pk)
    if params.creator_pk is not None:
        query = query.where(
            Video.channel_pk.in_(select(Channel.id).where(Channel.creator_pk == params.creator_pk))
        )
    if params.kind:
        query = query.where(Video.content_kind == params.kind)
    if params.integrity:
        query = query.where(Video.integrity == params.integrity)
    if params.watch == "watched":
        query = query.where(WatchProgress.watched.is_(True))
    elif params.watch == "unwatched":
        query = query.where(or_(WatchProgress.video_pk.is_(None), WatchProgress.watched.is_(False)))
    elif params.watch == "in_progress":
        query = query.where(WatchProgress.watched.is_(False), WatchProgress.position_seconds > 0)

    include = params.tags + (params.preset_tags if use_preset else [])
    exclude = params.exclude_tags + (params.preset_exclude_tags if use_preset else [])
    for condition in tag_service.conditions(include, exclude):
        query = query.where(condition)
    return query


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_video(db: DbSession, video_pk: int) -> Video | None:
    return db.scalars(with_relations(select(Video).where(Video.id == video_pk))).first()


def continue_watching(db: DbSession, limit: int) -> list[Video]:
    query = (
        select(Video)
        .join(WatchProgress, WatchProgress.video_pk == Video.id)
        .where(WatchProgress.watched.is_(False), WatchProgress.position_seconds > 0)
        .order_by(WatchProgress.last_watched_at.desc())
        .limit(limit)
    )
    return list(db.scalars(with_relations(query)).all())


def related(db: DbSession, video: Video, limit: int) -> tuple[Video | None, list[Video]]:
    """Up next = the following upload from the same channel; plus more from the channel."""
    if video.channel_pk is None:
        return None, []
    same_channel = select(Video).where(Video.channel_pk == video.channel_pk, Video.id != video.id)
    up_next = None
    if video.upload_date is not None:
        up_next = db.scalars(
            with_relations(
                same_channel.where(
                    or_(
                        Video.upload_date > video.upload_date,
                        and_(Video.upload_date == video.upload_date, Video.id > video.id),
                    )
                )
                .order_by(Video.upload_date.asc(), Video.id.asc())
                .limit(1)
            )
        ).first()
    more = db.scalars(
        with_relations(
            same_channel.order_by(Video.upload_date.desc().nulls_last(), Video.id.desc()).limit(
                limit
            )
        )
    ).all()
    return up_next, [v for v in more if up_next is None or v.id != up_next.id]


def subtitle_langs(settings: Settings, video: Video) -> list[str]:
    try:
        directory = archive.resolve_inside(settings.archive_root, video.directory)
    except ValueError:
        return []
    return sorted(p.stem for p in (directory / "subtitles").glob("*.vtt"))


def collection_ids(db: DbSession, video_pk: int) -> list[int]:
    return list(
        db.scalars(select(CollectionItem.collection_pk).where(CollectionItem.video_pk == video_pk))
    )


def _progress_row(db: DbSession, video: Video) -> WatchProgress:
    if video.progress is None:
        video.progress = WatchProgress(video_pk=video.id)
        db.flush()
    return video.progress


def set_progress(db: DbSession, video: Video, position: float) -> WatchProgress:
    row = _progress_row(db, video)
    duration = video.duration_seconds
    if duration:
        position = min(position, float(duration))
    row.position_seconds = position
    row.last_watched_at = utcnow()
    if duration and position >= duration * WATCHED_FRACTION and not row.watched:
        row.watched = True
        row.watched_at = utcnow()
    return row


def set_watched(db: DbSession, video: Video, watched: bool) -> WatchProgress:
    row = _progress_row(db, video)
    row.watched = watched
    row.watched_at = utcnow() if watched else None
    if not watched:
        row.position_seconds = 0.0
    row.last_watched_at = utcnow()
    return row


def delete_video(db: DbSession, settings: Settings, video: Video) -> Path:
    """Remove from the index; channel checks will not re-queue it. Returns the item directory
    so the caller can remove files after committing (a failed removal then leaves files a
    rescan can re-index, never a DB row pointing at nothing)."""
    directory = archive.video_dir(settings.archive_root, video.platform, video.video_id)
    channel_service.ignore(db, video.platform, video.video_id, "deleted")
    db.delete(video)
    return directory


def stats(db: DbSession, settings: Settings) -> dict[str, Any]:
    def grouped(column) -> dict[str, int]:
        return {k: v for k, v in db.execute(select(column, func.count()).group_by(column)).all()}

    try:
        usage = shutil.disk_usage(settings.archive_root)
        free, total = usage.free, usage.total
    except OSError:
        free = total = None
    return {
        "videos": db.scalar(select(func.count(Video.id))) or 0,
        "total_bytes": db.scalar(select(func.coalesce(func.sum(Video.media_size), 0))) or 0,
        "channels": db.scalar(select(func.count(Channel.id))) or 0,
        "watched_channels": db.scalar(
            select(func.count(Channel.id)).where(Channel.watch_enabled.is_(True))
        )
        or 0,
        "creators": db.scalar(select(func.count(Creator.id))) or 0,
        "collections": db.scalar(select(func.count(Collection.id))) or 0,
        "by_kind": grouped(Video.content_kind),
        "by_integrity": grouped(Video.integrity),
        "jobs": grouped(Job.status),
        "archive_free_bytes": free,
        "archive_total_bytes": total,
    }
