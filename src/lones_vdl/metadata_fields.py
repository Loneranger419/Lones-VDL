"""Extract browse fields and incompleteness flags from yt-dlp source metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "unknown"


@dataclass(frozen=True)
class BrowseFields:
    channel: str | None
    channel_id: str | None
    upload_date: str | None  # YYYYMMDD when known from source
    title: str | None
    url: str | None
    gaps: tuple[str, ...]
    incomplete: bool


def parse_upload_date(source: dict[str, Any]) -> str | None:
    raw = source.get("upload_date")
    if isinstance(raw, str) and re.fullmatch(r"\d{8}", raw):
        return raw
    # timestamp seconds
    for key in ("release_timestamp", "timestamp"):
        value = source.get(key)
        if isinstance(value, (int, float)) and value > 0:
            from datetime import UTC, datetime

            return datetime.fromtimestamp(int(value), tz=UTC).strftime("%Y%m%d")
    return None


def extract_browse_fields(
    source: dict[str, Any],
    *,
    fallback_url: str | None = None,
) -> BrowseFields:
    title = source.get("title") if isinstance(source.get("title"), str) else None
    channel = None
    for key in ("channel", "uploader", "creator"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            channel = value.strip()
            break

    channel_id = None
    for key in ("channel_id", "uploader_id"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            channel_id = value.strip()
            break
    if channel_id is None and channel:
        channel_id = f"name:{_slug(channel)}"

    upload_date = parse_upload_date(source)
    url = None
    for key in ("webpage_url", "original_url"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            url = value.strip()
            break
    if url is None:
        url = fallback_url

    gaps: list[str] = []
    if not title:
        gaps.append("title")
    if not channel:
        gaps.append("channel")
    if not channel_id:
        gaps.append("channel_id")
    if not upload_date:
        gaps.append("upload_date")

    return BrowseFields(
        channel=channel,
        channel_id=channel_id,
        upload_date=upload_date,
        title=title,
        url=url,
        gaps=tuple(gaps),
        incomplete=bool(gaps),
    )


def sort_date_value(*, upload_date: str | None, archived_at: str) -> str:
    """Lexicographically sortable date key (YYYYMMDD preferred)."""
    if upload_date and re.fullmatch(r"\d{8}", upload_date):
        return upload_date
    # archived_at ISO → YYYYMMDD
    digits = re.sub(r"\D", "", archived_at)[:8]
    return digits if len(digits) == 8 else "00000000"


_SOURCE_SNAPSHOT_KEYS = (
    "id",
    "title",
    "fulltitle",
    "description",
    "channel",
    "channel_id",
    "uploader",
    "uploader_id",
    "upload_date",
    "release_timestamp",
    "timestamp",
    "duration",
    "width",
    "height",
    "fps",
    "ext",
    "format",
    "format_id",
    "vcodec",
    "acodec",
    "abr",
    "vbr",
    "tbr",
    "filesize_approx",
    "webpage_url",
    "original_url",
    "thumbnail",
    "tags",
    "categories",
    "chapters",
    "view_count",
    "like_count",
    "comment_count",
    "availability",
    "live_status",
    "was_live",
    "language",
    "subtitles",
    "automatic_captions",
)


def source_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep a portable subset of yt-dlp metadata."""
    return {key: raw[key] for key in _SOURCE_SNAPSHOT_KEYS if key in raw}
