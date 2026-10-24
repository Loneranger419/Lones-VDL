"""Video tags (from yt-dlp's `tags`) and the filters built on them."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement, func, not_, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db.models import Video, VideoTag
from lones_vdl.storage import archive

logger = logging.getLogger(__name__)

MAX_TAG_LENGTH = 100
MAX_TAGS_PER_VIDEO = 60


def key(tag: str) -> str:
    """How tags are compared: trimmed, lowercase, inner spaces collapsed."""
    return " ".join(tag.lower().split())[:MAX_TAG_LENGTH]


def normalize(raw: Any) -> list[tuple[str, str]]:
    """(key, label) pairs from yt-dlp's `tags`, without duplicates, in their original order."""
    if not isinstance(raw, list):
        return []
    seen: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, str):
            continue
        label = " ".join(item.split())[:MAX_TAG_LENGTH]
        tag = key(label)
        if tag and tag not in seen:
            seen[tag] = label
        if len(seen) >= MAX_TAGS_PER_VIDEO:
            break
    return list(seen.items())


def set_tags(db: DbSession, video: Video, raw: Any) -> None:
    """Replace the video's tags with those in `raw` and mark it as indexed."""
    pairs = normalize(raw)
    video.tag_rows = [VideoTag(video_pk=video.id, tag=tag, label=label) for tag, label in pairs]
    video.tags_indexed = True


def clean(tags: Iterable[str]) -> list[str]:
    """Filter input: keys, without blanks or duplicates."""
    return list(dict.fromkeys(t for t in (key(x) for x in tags) if t))


def conditions(include: Iterable[str], exclude: Iterable[str]) -> list[ColumnElement[bool]]:
    """WHERE clauses: has every `include` tag and none of the `exclude` tags."""
    result: list[ColumnElement[bool]] = []
    for tag in clean(include):
        result.append(Video.id.in_(select(VideoTag.video_pk).where(VideoTag.tag == tag)))
    excluded = clean(exclude)
    if excluded:
        result.append(
            not_(Video.id.in_(select(VideoTag.video_pk).where(VideoTag.tag.in_(excluded))))
        )
    return result


def popular(db: DbSession, q: str | None, limit: int) -> list[tuple[str, str, int]]:
    """(key, label, videos) for the most used tags, optionally containing `q`."""
    query = select(VideoTag.tag, func.min(VideoTag.label), func.count()).group_by(VideoTag.tag)
    if q and (needle := key(q)):
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(VideoTag.tag.like(f"%{escaped}%", escape="\\"))
    rows = db.execute(query.order_by(func.count().desc(), VideoTag.tag).limit(limit)).all()
    return [(tag, label, count) for tag, label, count in rows]


def backfill(settings: Settings, sessions: sessionmaker) -> int:
    """Read tags from info.json for videos archived before tags were indexed. Returns how many."""
    done = 0
    with sessions() as db:
        pending = list(db.execute(select(Video.id, Video.directory).where(~Video.tags_indexed)))
    for video_pk, directory in pending:
        raw: Any = None
        try:
            path = archive.resolve_inside(settings.archive_root, directory) / archive.INFO_FILE
            raw = json.loads(path.read_text(encoding="utf-8")).get("tags")
        except (OSError, ValueError):
            pass  # no readable info.json: the video simply has no tags
        with sessions.begin() as db:
            video = db.get(Video, video_pk)
            if video is not None:
                set_tags(db, video, raw)
                done += 1
    if done:
        logger.info("indexed tags for %d videos", done)
    return done


def has_filter(include: Iterable[str], exclude: Iterable[str]) -> bool:
    return bool(clean(include) or clean(exclude))
