"""Creators group channels (possibly across platforms). Linking is manual."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import selectinload

from lones_vdl.db.models import Channel, Creator, Video


class CreatorError(ValueError):
    pass


def set_channels(db: DbSession, creator: Creator, channel_ids: list[int]) -> None:
    """Make exactly these channels belong to the creator (moving them from any other)."""
    channels = db.scalars(select(Channel).where(Channel.id.in_(channel_ids))).all()
    missing = sorted(set(channel_ids) - {c.id for c in channels})
    if missing:
        raise CreatorError(f"unknown channel ids: {missing[:20]}")
    for channel in list(creator.channels):
        if channel.id not in channel_ids:
            channel.creator = None
    for channel in channels:
        channel.creator = creator


def name_taken(db: DbSession, name: str, *, exclude: int | None = None) -> bool:
    query = select(Creator.id).where(func.lower(Creator.name) == name.lower())
    if exclude is not None:
        query = query.where(Creator.id != exclude)
    return db.scalars(query).first() is not None


def listing(db: DbSession, creators: list[Creator] | None = None) -> list[dict[str, Any]]:
    if creators is None:
        creators = list(
            db.scalars(
                select(Creator)
                .options(selectinload(Creator.channels))
                .order_by(func.lower(Creator.name))
            )
        )
    counts = dict(
        db.execute(
            select(Channel.creator_pk, func.count(Video.id))
            .join(Video, Video.channel_pk == Channel.id)
            .where(Channel.creator_pk.is_not(None))
            .group_by(Channel.creator_pk)
        ).all()
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "notes": c.notes,
            "created_at": c.created_at,
            "channels": c.channels,
            "video_count": counts.get(c.id, 0),
        }
        for c in creators
    ]
