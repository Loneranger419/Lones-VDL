from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from lones_vdl.platforms.base import ParsedUrl, UrlKind

NAME = "youtube"

_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
# Path prefixes whose next segment is a video id.
_VIDEO_PATHS = {"shorts", "live", "embed", "v", "e"}
# Channel tabs that still mean "the channel" when given as a URL.
_CHANNEL_TABS = {"videos", "streams", "shorts", "featured", "live", ""}


class YouTube:
    name = NAME

    def video_url(self, video_id: str) -> str:
        return f"https://www.youtube.com/watch?v={video_id}"

    def parse_url(self, url: str) -> ParsedUrl | None:
        text = url.strip()
        if not text:
            return None
        if "://" not in text:
            text = "https://" + text
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"}:
            return None
        host = (parsed.hostname or "").lower()
        segments = [s for s in parsed.path.split("/") if s]
        query = parse_qs(parsed.query)

        if host in _SHORT_HOSTS:
            if segments and _VIDEO_ID.match(segments[0]):
                return self._video(segments[0])
            return None
        if host not in _HOSTS:
            return None

        # A watch URL with list= is treated as the video; playlists use /playlist?list=.
        if segments[:1] == ["watch"]:
            video_id = (query.get("v") or [""])[0]
            return self._video(video_id) if _VIDEO_ID.match(video_id) else None
        if len(segments) >= 2 and segments[0] in _VIDEO_PATHS and _VIDEO_ID.match(segments[1]):
            return self._video(segments[1])
        if segments[:1] == ["playlist"]:
            list_id = (query.get("list") or [""])[0]
            if _PLAYLIST_ID.match(list_id):
                return ParsedUrl(
                    NAME,
                    UrlKind.PLAYLIST,
                    list_id,
                    f"https://www.youtube.com/playlist?list={list_id}",
                )
            return None
        return self._channel(segments)

    def _video(self, video_id: str) -> ParsedUrl:
        return ParsedUrl(NAME, UrlKind.VIDEO, video_id, self.video_url(video_id))

    def _channel(self, segments: list[str]) -> ParsedUrl | None:
        if not segments:
            return None
        head = segments[0]
        if head.startswith("@") and len(head) > 1:
            tail = segments[1:]
            url, channel_id = f"https://www.youtube.com/{head}", None
        elif head == "channel" and len(segments) >= 2 and _CHANNEL_ID.match(segments[1]):
            channel_id, tail = segments[1], segments[2:]
            url = f"https://www.youtube.com/channel/{channel_id}"
        elif head in {"c", "user"} and len(segments) >= 2:
            tail = segments[2:]
            url, channel_id = f"https://www.youtube.com/{head}/{segments[1]}", None
        else:
            return None
        if len(tail) > 1 or (tail and tail[0].lower() not in _CHANNEL_TABS):
            return None
        return ParsedUrl(NAME, UrlKind.CHANNEL, channel_id, url)
