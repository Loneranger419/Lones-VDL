"""Chapters and "most replayed" sections, read from a video's archived info.json.

Nothing is copied into the database: info.json is the source of truth, and a video without these
fields simply has none."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from lones_vdl.config import Settings
from lones_vdl.db.models import Video
from lones_vdl.platforms import PLATFORMS
from lones_vdl.storage import archive

logger = logging.getLogger(__name__)

MAX_TITLE = 200
# A video missing chapters or "most replayed" data is looked at again when it is played, at most
# this often ...
CHECK_INTERVAL = timedelta(hours=24)
# ... until it is this old, after which it is assumed never to get them. Replay data only appears
# once a video has had enough views, so it is waited for longer.
GIVE_UP_CHAPTERS_AFTER = timedelta(days=14)
GIVE_UP_HEATMAP_AFTER = timedelta(days=30)
MAX_HEATMAP_POINTS = 400


@dataclass(frozen=True)
class Chapter:
    start: float
    end: float
    title: str


@dataclass(frozen=True)
class HeatPoint:
    start: float
    end: float
    value: float  # 0..1, how often this stretch was replayed relative to the rest


@dataclass(frozen=True)
class VideoChapters:
    chapters: list[Chapter] = field(default_factory=list)
    heatmap: list[HeatPoint] = field(default_factory=list)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value >= 0 and value == value else None  # NaN is not >= 0


def parse(info: dict[str, Any], duration: float | None) -> VideoChapters:
    """Clean chapters/heatmap from yt-dlp's info dict. Bad entries are dropped, not fatal."""
    chapters: list[Chapter] = []
    raw = info.get("chapters")
    items = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    starts = [(_number(c.get("start_time")), c) for c in items]
    starts = sorted((s, c) for s, c in starts if s is not None and (not duration or s < duration))
    for index, (start, item) in enumerate(starts):
        following = starts[index + 1][0] if index + 1 < len(starts) else None
        end = _number(item.get("end_time"))
        end = following if following is not None else (end if end is not None else duration)
        if end is None or end <= start:
            continue
        title = " ".join(str(item.get("title") or "").split())[:MAX_TITLE]
        chapters.append(Chapter(start, end, title or f"Chapter {index + 1}"))

    heat: list[HeatPoint] = []
    raw_heat = info.get("heatmap")
    if isinstance(raw_heat, list):
        for item in raw_heat[:MAX_HEATMAP_POINTS]:
            if not isinstance(item, dict):
                continue
            start, end, value = (
                _number(item.get("start_time")),
                _number(item.get("end_time")),
                _number(item.get("value")),
            )
            if start is None or end is None or value is None or end <= start:
                continue
            heat.append(HeatPoint(start, end, min(value, 1.0)))
    return VideoChapters(chapters, heat)


@lru_cache(maxsize=256)
def _read(path: str, modified: float, size: int, duration: float | None) -> VideoChapters:
    """Cached by file identity, so a rewritten info.json is picked up and reads stay cheap."""
    try:
        info = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("could not read chapters from %s", path)
        return VideoChapters()
    return parse(info, duration) if isinstance(info, dict) else VideoChapters()


def load(settings: Settings, video: Video) -> VideoChapters:
    try:
        path = archive.resolve_inside(settings.archive_root, video.directory) / archive.INFO_FILE
        stat = path.stat()
    except (OSError, ValueError):
        return VideoChapters()
    duration = float(video.duration_seconds) if video.duration_seconds else None
    return _read(str(path), stat.st_mtime, stat.st_size, duration)


def _timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    return f"{hours:02d}:{minutes:02d}:{rest // 1000:02d}.{rest % 1000:03d}"


def _cue_text(title: str) -> str:
    return title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_vtt(chapters: list[Chapter]) -> str:
    """A WebVTT chapters track, which the player draws on its timeline."""
    lines = ["WEBVTT", ""]
    for number, chapter in enumerate(chapters, 1):
        lines += [
            str(number),
            f"{_timestamp(chapter.start)} --> {_timestamp(chapter.end)}",
            _cue_text(chapter.title),
            "",
        ]
    return "\n".join(lines)


def _age(video: Video, now: datetime) -> timedelta:
    """How long ago the video was published (when it was archived, if its date is unknown)."""
    if video.upload_date is not None:
        published = datetime(
            video.upload_date.year, video.upload_date.month, video.upload_date.day, tzinfo=UTC
        )
    else:
        published = video.archived_at
    return now - published


def check_due(video: Video, chapter_count: int, heat_count: int, now: datetime) -> bool:
    """Should the site be asked again for this video's chapters?

    Creators often add chapters some time after publishing, and replay data comes with views. So
    a recent video missing either is re-checked when played, at most daily; once it is past the
    give-up age for what it lacks (14 days chapters, 30 days replay data) that is assumed final."""
    if video.platform not in PLATFORMS:
        return False
    age = _age(video, now)
    wants_chapters = chapter_count == 0 and age < GIVE_UP_CHAPTERS_AFTER
    wants_heatmap = heat_count == 0 and age < GIVE_UP_HEATMAP_AFTER
    if not (wants_chapters or wants_heatmap):
        return False
    last = video.chapters_checked_at
    return last is None or now - last >= CHECK_INTERVAL
