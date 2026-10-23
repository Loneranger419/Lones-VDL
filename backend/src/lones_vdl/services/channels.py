"""Channel records, avatars, and the "what do we already have" checks used by expansion."""

from __future__ import annotations

import logging
import os
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from lones_vdl.db.models import ACTIVE_JOB_STATUSES, Channel, IgnoredVideo, Job, JobKind, Video

logger = logging.getLogger(__name__)

TABS = ("videos", "streams", "shorts")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_IMAGE_EXTS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def channel_fields(info: dict[str, Any]) -> dict[str, str | None]:
    """Channel identity from a video info dict or a channel/playlist listing."""
    handle = info.get("uploader_id")
    return {
        "channel_id": info.get("channel_id") or None,
        "name": info.get("channel") or info.get("uploader"),
        "handle": handle if isinstance(handle, str) and handle.startswith("@") else None,
        "url": info.get("channel_url") or info.get("uploader_url"),
    }


def upsert_channel(db: DbSession, platform: str, fields: dict[str, Any]) -> Channel | None:
    channel_id = fields.get("channel_id")
    if not channel_id:
        return None
    channel = db.scalars(
        select(Channel).where(Channel.platform == platform, Channel.channel_id == channel_id)
    ).first()
    if channel is None:
        channel = Channel(platform=platform, channel_id=channel_id)
        db.add(channel)
    for key in ("name", "handle", "url", "description"):
        value = fields.get(key)
        if value:
            setattr(channel, key, value)
    db.flush()
    return channel


def channel_base_url(channel: Channel) -> str:
    if channel.handle:
        return f"https://www.youtube.com/{channel.handle}"
    return f"https://www.youtube.com/channel/{channel.channel_id}"


def enabled_tabs(channel: Channel) -> list[str]:
    flags = {
        "videos": channel.watch_videos,
        "streams": channel.watch_streams,
        "shorts": channel.watch_shorts,
    }
    return [tab for tab in TABS if flags[tab]]


def known_video_ids(db: DbSession, platform: str, ids: Iterable[str]) -> set[str]:
    """Ids that must not be queued again: archived, ignored, or already in an active job."""
    wanted = list(set(ids))
    known: set[str] = set()
    for start in range(0, len(wanted), 500):  # stay under SQLite's variable limit
        chunk = wanted[start : start + 500]
        known.update(
            db.scalars(
                select(Video.video_id).where(Video.platform == platform, Video.video_id.in_(chunk))
            )
        )
        known.update(
            db.scalars(
                select(IgnoredVideo.video_id).where(
                    IgnoredVideo.platform == platform, IgnoredVideo.video_id.in_(chunk)
                )
            )
        )
        known.update(
            v
            for v in db.scalars(
                select(Job.video_id).where(
                    Job.platform == platform,
                    Job.kind == JobKind.DOWNLOAD,
                    Job.video_id.in_(chunk),
                    Job.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
            if v
        )
    return known


def ignore(db: DbSession, platform: str, video_id: str, reason: str) -> None:
    exists = db.scalars(
        select(IgnoredVideo).where(
            IgnoredVideo.platform == platform, IgnoredVideo.video_id == video_id
        )
    ).first()
    if exists is None:
        db.add(IgnoredVideo(platform=platform, video_id=video_id, reason=reason))
    else:
        exists.reason = reason


def unignore(db: DbSession, platform: str, video_id: str) -> None:
    row = db.scalars(
        select(IgnoredVideo).where(
            IgnoredVideo.platform == platform, IgnoredVideo.video_id == video_id
        )
    ).first()
    if row is not None:
        db.delete(row)


def video_stats(db: DbSession) -> dict[int, tuple[int, int]]:
    """channel pk -> (archived video count, total media bytes)."""
    rows = db.execute(
        select(Video.channel_pk, func.count(Video.id), func.coalesce(func.sum(Video.media_size), 0))
        .where(Video.channel_pk.is_not(None))
        .group_by(Video.channel_pk)
    ).all()
    return {pk: (count, size) for pk, count, size in rows}


def active_expand_for_channel(db: DbSession, channel_pk: int) -> Job | None:
    return db.scalars(
        select(Job).where(
            Job.kind == JobKind.EXPAND,
            Job.channel_pk == channel_pk,
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
    ).first()


def pick_thumbnail(meta: dict[str, Any], kind: str) -> str | None:
    """Channel avatar/banner URL from a listing's thumbnails (yt-dlp ids *_uncropped)."""
    thumbs = [t for t in meta.get("thumbnails") or [] if isinstance(t, dict) and t.get("url")]
    for thumb in thumbs:
        if thumb.get("id") == f"{kind}_uncropped":
            return thumb["url"]
    return None


def fetch_bytes(url: str) -> tuple[bytes, str]:
    """HTTPS GET with a size cap. Separate function so tests can replace it."""
    if not url.startswith("https://"):
        raise ValueError("only https image URLs are fetched")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Lones-VDL"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 (https only)
        data = response.read(MAX_IMAGE_BYTES + 1)
        content_type = response.headers.get_content_type()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    return data, content_type


def save_image(url: str, dest_stem: Path) -> Path | None:
    """Download an image to dest_stem + extension. Failures are logged, not raised."""
    try:
        data, content_type = fetch_bytes(url)
    except Exception as exc:  # noqa: BLE001 - avatars are cosmetic
        logger.warning("could not fetch %s: %s", url, exc)
        return None
    ext = _IMAGE_EXTS.get(content_type)
    if ext is None:
        logger.warning("unexpected image type %s for %s", content_type, url)
        return None
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    for old in dest_stem.parent.glob(dest_stem.name + ".*"):
        old.unlink()
    dest = dest_stem.with_suffix(ext)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return dest
