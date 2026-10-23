"""Per-platform URL parsing. Add Twitch by registering another Platform here."""

from lones_vdl.platforms.base import ParsedUrl, Platform, UrlKind
from lones_vdl.platforms.youtube import YouTube

PLATFORMS: dict[str, Platform] = {"youtube": YouTube()}


def parse_url(url: str) -> ParsedUrl | None:
    for platform in PLATFORMS.values():
        parsed = platform.parse_url(url)
        if parsed is not None:
            return parsed
    return None


def get_platform(name: str) -> Platform:
    return PLATFORMS[name]


__all__ = ["PLATFORMS", "ParsedUrl", "Platform", "UrlKind", "get_platform", "parse_url"]
