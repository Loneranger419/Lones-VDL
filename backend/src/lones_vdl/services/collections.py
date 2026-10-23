"""User-made ordered lists of archived videos."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from lones_vdl.db import utcnow
from lones_vdl.db.models import Collection, CollectionItem, Video
from lones_vdl.services.library import with_relations


class CollectionError(ValueError):
    pass


def summaries(db: DbSession) -> list[dict[str, Any]]:
    # SQLite returns the bare video_pk from the row holding min(position).
    rows = db.execute(
        select(
            CollectionItem.collection_pk,
            func.count(),
            func.min(CollectionItem.position),
            CollectionItem.video_pk,
        ).group_by(CollectionItem.collection_pk)
    ).all()
    stats = {pk: (count, cover) for pk, count, _, cover in rows}
    return [
        summary(c, *stats.get(c.id, (0, None)))
        for c in db.scalars(select(Collection).order_by(func.lower(Collection.name)))
    ]


def summary(collection: Collection, count: int, cover: int | None) -> dict[str, Any]:
    return {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
        "item_count": count,
        "cover_video_pk": cover,
    }


def detail(db: DbSession, collection: Collection) -> dict[str, Any]:
    videos = db.scalars(
        with_relations(
            select(Video)
            .join(CollectionItem, CollectionItem.video_pk == Video.id)
            .where(CollectionItem.collection_pk == collection.id)
            .order_by(CollectionItem.position, CollectionItem.added_at)
        )
    ).all()
    return {
        **summary(collection, len(videos), videos[0].id if videos else None),
        "videos": videos,
    }


def _check_videos(db: DbSession, video_ids: list[int]) -> None:
    found = set(db.scalars(select(Video.id).where(Video.id.in_(video_ids))))
    missing = sorted(set(video_ids) - found)
    if missing:
        raise CollectionError(f"unknown video ids: {missing[:20]}")


def add_items(db: DbSession, collection: Collection, video_ids: list[int]) -> int:
    """Append videos not already in the collection. Returns how many were added."""
    _check_videos(db, video_ids)
    present = {item.video_pk for item in collection.items}
    position = max((item.position for item in collection.items), default=-1)
    added = 0
    for pk in dict.fromkeys(video_ids):
        if pk in present:
            continue
        position += 1
        collection.items.append(CollectionItem(video_pk=pk, position=position))
        added += 1
    collection.updated_at = utcnow()
    return added


def remove_item(collection: Collection, video_pk: int) -> bool:
    for item in collection.items:
        if item.video_pk == video_pk:
            collection.items.remove(item)
            collection.updated_at = utcnow()
            return True
    return False


def reorder(collection: Collection, video_ids: list[int]) -> None:
    current = {item.video_pk: item for item in collection.items}
    if sorted(video_ids) != sorted(current) or len(set(video_ids)) != len(video_ids):
        raise CollectionError("video_ids must list every item in the collection exactly once")
    for position, pk in enumerate(video_ids):
        current[pk].position = position
    collection.updated_at = utcnow()
