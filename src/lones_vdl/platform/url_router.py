"""Classify archive URLs by platform and job/content kind."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse

from lones_vdl.errors import PermanentDownloadError
from lones_vdl.storage import PLATFORM_TWITCH, PLATFORM_YOUTUBE

UrlKind = Literal["video", "playlist", "channel"]
ContentKind = Literal["video", "vod", "clip"]

_YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/))([A-Za-z0-9_-]{11})"
)
_CHANNEL_PATH_RE = re.compile(
    r"youtube\.com/(?:@[\w.-]+|(?:channel|c|user)/[^/?#]+)",
    re.IGNORECASE,
)
_TWITCH_VOD_RE = re.compile(r"(?:www\.)?twitch\.tv/videos/(\d+)", re.IGNORECASE)
_TWITCH_CLIP_HOST_RE = re.compile(
    r"(?:clips\.twitch\.tv/|twitch\.tv/[^/?#]+/clip/)([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_TWITCH_CHANNEL_RE = re.compile(
    r"(?:www\.)?twitch\.tv/([A-Za-z0-9_]{3,25})(?:/|$|\?)",
    re.IGNORECASE,
)
_TWITCH_RESERVED = frozenset(
    {
        "videos",
        "directory",
        "downloads",
        "jobs",
        "settings",
        "subscriptions",
        "inventory",
        "wallet",
        "p",
        "turbo",
        "prime",
        "search",
        "popout",
        "embed",
        "login",
        "signup",
        "clips",
    }
)


@dataclass(frozen=True)
class ClassifiedUrl:
    platform: str
    kind: UrlKind
    """Job routing kind: single media jobs use ``video``; lists use playlist/channel."""

    content_kind: ContentKind | None
    """Archive content kind for singles; None for playlist/channel expand."""

    hint_id: str | None
    url: str


def parse_youtube_id(url: str) -> str | None:
    match = _YOUTUBE_ID_RE.search(url)
    return match.group(1) if match else None


def parse_twitch_vod_id(url: str) -> str | None:
    match = _TWITCH_VOD_RE.search(url)
    return match.group(1) if match else None


def parse_twitch_clip_id(url: str) -> str | None:
    match = _TWITCH_CLIP_HOST_RE.search(url)
    return match.group(1) if match else None


def _host(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def _is_youtube_host(host: str) -> bool:
    return host in {"youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com"}


def _is_twitch_host(host: str) -> bool:
    return host in {"twitch.tv", "clips.twitch.tv", "m.twitch.tv"}


def classify_youtube_url(url: str) -> UrlKind:
    """Classify a YouTube URL for enqueue routing. watch?v=&list= is still a video."""
    lowered = url.lower()
    if _CHANNEL_PATH_RE.search(lowered):
        return "channel"
    if "playlist" in lowered or re.search(r"[?&]list=", lowered):
        if parse_youtube_id(url) and re.search(r"[?&]v=", lowered):
            return "video"
        if parse_youtube_id(url) and "youtu.be/" in lowered and "list=" in lowered:
            return "video"
        return "playlist"
    return "video"


def _twitch_is_clips_listing(url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    query = parse_qs(parsed.query)
    if "/clips" in path or path.rstrip("/").endswith("/clip"):
        # /user/clip/Slug is a single clip, not a listing
        if re.search(r"/clip/[A-Za-z0-9_-]+", path, re.I):
            return False
        return True
    filters = [v.lower() for values in query.values() for v in values]
    if "clips" in filters or any(v == "clips" for v in query.get("filter", [])):
        return True
    return False


def _classify_twitch(url: str) -> ClassifiedUrl:
    if _twitch_is_clips_listing(url):
        raise PermanentDownloadError(
            "Twitch channel clip listings are not supported for expand. "
            "Enqueue individual clip URLs instead.",
            code="unsupported_url",
        )
    clip_id = parse_twitch_clip_id(url)
    if clip_id:
        return ClassifiedUrl(
            platform=PLATFORM_TWITCH,
            kind="video",
            content_kind="clip",
            hint_id=clip_id,
            url=url,
        )
    vod_id = parse_twitch_vod_id(url)
    if vod_id:
        return ClassifiedUrl(
            platform=PLATFORM_TWITCH,
            kind="video",
            content_kind="vod",
            hint_id=vod_id,
            url=url,
        )
    match = _TWITCH_CHANNEL_RE.search(url)
    if match:
        login = match.group(1)
        if login.lower() not in _TWITCH_RESERVED:
            return ClassifiedUrl(
                platform=PLATFORM_TWITCH,
                kind="channel",
                content_kind=None,
                hint_id=login.lower(),
                url=url,
            )
    raise PermanentDownloadError(
        f"Unrecognized Twitch URL (expected VOD, clip, or channel): {url}",
        code="unsupported_url",
    )


def classify_url(url: str) -> ClassifiedUrl:
    """Classify a YouTube or Twitch URL for enqueue routing."""
    host = _host(url)
    if not host:
        raise PermanentDownloadError("URL is missing a host", code="unsupported_url")
    if _is_youtube_host(host):
        kind = classify_youtube_url(url)
        hint = parse_youtube_id(url) if kind == "video" else None
        return ClassifiedUrl(
            platform=PLATFORM_YOUTUBE,
            kind=kind,
            content_kind="video" if kind == "video" else None,
            hint_id=hint,
            url=url,
        )
    if _is_twitch_host(host):
        return _classify_twitch(url)
    raise PermanentDownloadError(
        f"Unsupported site '{host}'. Supported: YouTube, Twitch.",
        code="unsupported_url",
    )


def twitch_vod_list_url(channel_login: str) -> str:
    login = channel_login.strip().lstrip("@")
    return f"https://www.twitch.tv/{login}/videos?filter=archives"


def normalize_list_url(classified: ClassifiedUrl) -> str:
    """Rewrite channel URLs to the listing yt-dlp should expand."""
    if classified.platform == PLATFORM_YOUTUBE and classified.kind == "channel":
        if re.search(r"youtube\.com/@[\w.-]+/?$", classified.url, re.I):
            return classified.url.rstrip("/") + "/videos"
        return classified.url
    if classified.platform == PLATFORM_TWITCH and classified.kind == "channel":
        login = classified.hint_id or ""
        if not login:
            match = _TWITCH_CHANNEL_RE.search(classified.url)
            login = match.group(1) if match else ""
        if login:
            return twitch_vod_list_url(login)
    return classified.url


def infer_content_kind(
    *,
    platform: str,
    url: str,
    raw: dict | None = None,
) -> ContentKind:
    """Infer content_kind for an archived item from URL and/or yt-dlp metadata."""
    try:
        classified = classify_url(url)
        if classified.content_kind:
            return classified.content_kind
    except PermanentDownloadError:
        pass
    if platform == PLATFORM_TWITCH:
        blob = " ".join(
            str(raw.get(key) or "")
            for key in ("extractor", "extractor_key", "ie_key", "_type", "webpage_url")
            if raw
        ).lower()
        if "clip" in blob:
            return "clip"
        return "vod"
    return "video"


def fallback_watch_url(platform: str, video_id: str) -> str | None:
    if platform == PLATFORM_YOUTUBE:
        return f"https://www.youtube.com/watch?v={video_id}"
    if platform == PLATFORM_TWITCH:
        if video_id.isdigit():
            return f"https://www.twitch.tv/videos/{video_id}"
        return f"https://clips.twitch.tv/{video_id}"
    return None


def watch_fallback_url(*, platform: str, channel_id: str, channel_url: str | None) -> str | None:
    if channel_url:
        return channel_url
    if platform == PLATFORM_YOUTUBE and channel_id.startswith("UC"):
        return f"https://www.youtube.com/channel/{channel_id}/videos"
    if platform == PLATFORM_TWITCH:
        return twitch_vod_list_url(channel_id)
    return None
