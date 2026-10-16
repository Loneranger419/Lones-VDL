"""Fetch and store per-channel avatar images under platform/_channels/."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lones_vdl.errors import LonesVdlError
from lones_vdl.platform.ytdlp import YtdlpAdapter
from lones_vdl.storage import channel_paths, find_channel_avatar

logger = logging.getLogger(__name__)


def channel_url_from_source(source: dict[str, Any]) -> str | None:
    for key in ("channel_url", "uploader_url"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def pick_avatar_url(raw: dict[str, Any]) -> str | None:
    """Prefer yt-dlp channel/playlist avatar thumbnail entries."""
    thumbs = raw.get("thumbnails")
    if isinstance(thumbs, list):
        preferred: str | None = None
        fallback: str | None = None
        for entry in thumbs:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            thumb_id = str(entry.get("id") or "")
            if "avatar" in thumb_id.lower():
                preferred = url.strip()
            fallback = url.strip()
        if preferred:
            return preferred
        if fallback:
            return fallback
    for key in ("thumbnail", "channel_thumbnail", "uploader_avatar_url"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def ensure_channel_avatar(
    *,
    archive_root: Path,
    platform: str,
    channel_id: str,
    channel_url: str | None,
    adapter: YtdlpAdapter,
) -> Path | None:
    """Return existing avatar or fetch once via yt-dlp. Best-effort (never raises)."""
    paths = channel_paths(archive_root, platform, channel_id)
    existing = find_channel_avatar(paths)
    if existing is not None:
        return existing
    if not channel_url:
        return None
    try:
        return adapter.download_channel_avatar(channel_url, dest_dir=paths.dir)
    except LonesVdlError as exc:
        logger.info("Channel avatar failed for %s: %s", channel_id, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — polish must not break archives
        logger.info("Channel avatar error for %s: %s", channel_id, exc)
        return None


def channel_has_avatar(archive_root: Path, platform: str, channel_id: str) -> bool:
    return find_channel_avatar(channel_paths(archive_root, platform, channel_id)) is not None


def resolve_channel_avatar_file(
    archive_root: Path,
    platform: str,
    channel_id: str,
) -> Path | None:
    return find_channel_avatar(channel_paths(archive_root, platform, channel_id))
