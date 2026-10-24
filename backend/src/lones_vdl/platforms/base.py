from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class UrlKind(StrEnum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    CHANNEL = "channel"


@dataclass(frozen=True)
class ParsedUrl:
    platform: str
    kind: UrlKind
    # Stable id when it can be read from the URL alone (video id, playlist id, channel id).
    # None for forms that need yt-dlp to resolve (e.g. @handles).
    id: str | None
    # Canonical URL to hand to yt-dlp.
    url: str
    # The URL names a short (a clip, on other platforms): short-form content with its own limits.
    short: bool = False


class Platform(Protocol):
    name: str

    def parse_url(self, url: str) -> ParsedUrl | None:
        """Return the parsed URL if this platform owns it, else None."""
        ...

    def video_url(self, video_id: str) -> str: ...
