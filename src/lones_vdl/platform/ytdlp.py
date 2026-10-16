"""yt-dlp adapter: metadata + download via CLI (mockable interface)."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from lones_vdl.errors import (
    AuthConfigError,
    PermanentDownloadError,
    TransientDownloadError,
)

logger = logging.getLogger(__name__)

# Common YouTube URL shapes for a fast local id parse (adapter still authoritative).
_YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/))([A-Za-z0-9_-]{11})"
)
_PLAYLIST_RE = re.compile(r"(?:[?&]list=|/playlist\?)([A-Za-z0-9_-]+)")
_CHANNEL_PATH_RE = re.compile(
    r"youtube\.com/(?:@[\w.-]+|(?:channel|c|user)/[^/?#]+)",
    re.IGNORECASE,
)

UrlKind = Literal["video", "playlist", "channel"]


@dataclass(frozen=True)
class VideoInfo:
    platform: str
    video_id: str
    url: str
    title: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class DownloadResult:
    info: VideoInfo
    media_path: Path
    thumbnail_paths: list[Path]
    subtitle_paths: list[Path]
    ytdlp_version: str | None


@dataclass(frozen=True)
class PlaylistEntry:
    video_id: str
    url: str
    title: str | None
    channel: str | None
    channel_id: str | None
    channel_url: str | None


@dataclass(frozen=True)
class PlaylistListing:
    kind: UrlKind
    list_id: str | None
    title: str | None
    url: str
    channel: str | None
    channel_id: str | None
    channel_url: str | None
    entries: tuple[PlaylistEntry, ...]


class YtdlpAdapter(Protocol):
    def extract_info(self, url: str) -> VideoInfo: ...

    def list_entries(self, url: str) -> PlaylistListing:
        """Flat-list playlist or channel uploads (no media download)."""

    def download_channel_avatar(self, channel_url: str, *, dest_dir: Path) -> Path | None:
        """Download a channel avatar into dest_dir as avatar.<ext>, or return None."""

    def download(
        self,
        url: str,
        *,
        output_dir: Path,
        quality_preference: str,
    ) -> DownloadResult: ...


def parse_youtube_id(url: str) -> str | None:
    match = _YOUTUBE_ID_RE.search(url)
    return match.group(1) if match else None


def classify_youtube_url(url: str) -> UrlKind:
    """Classify URL for enqueue routing. watch?v=&list= is still a single video."""
    lowered = url.lower()
    if _CHANNEL_PATH_RE.search(lowered):
        return "channel"
    if "playlist" in lowered or re.search(r"[?&]list=", lowered):
        # Bare playlist pages, or list= without a primary video id intent.
        if parse_youtube_id(url) and re.search(r"[?&]v=", lowered):
            return "video"
        if parse_youtube_id(url) and "youtu.be/" in lowered and "list=" in lowered:
            return "video"
        return "playlist"
    return "video"


def _entry_from_raw(
    entry: dict[str, Any],
    *,
    fallback_channel: dict[str, Any],
) -> PlaylistEntry | None:
    video_id = str(entry.get("id") or entry.get("url") or "")
    if not video_id or video_id.startswith(("http://", "https://")):
        # Sometimes id is missing and url is a full watch URL
        parsed = parse_youtube_id(str(entry.get("url") or entry.get("webpage_url") or ""))
        video_id = parsed or ""
    if not video_id or len(video_id) < 6:
        return None
    # Skip non-video playlist tabs
    entry_type = str(entry.get("_type") or entry.get("ie_key") or "").lower()
    if entry_type in {"playlist", "channel"}:
        return None
    webpage = entry.get("webpage_url") or entry.get("url")
    if isinstance(webpage, str) and webpage.startswith("http"):
        watch_url = webpage
    else:
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
    channel = entry.get("channel") or entry.get("uploader") or fallback_channel.get("channel")
    channel_id = (
        entry.get("channel_id") or entry.get("uploader_id") or fallback_channel.get("channel_id")
    )
    channel_url = (
        entry.get("channel_url") or entry.get("uploader_url") or fallback_channel.get("channel_url")
    )
    title = entry.get("title") if isinstance(entry.get("title"), str) else None
    return PlaylistEntry(
        video_id=video_id,
        url=watch_url,
        title=title,
        channel=str(channel) if channel else None,
        channel_id=str(channel_id) if channel_id else None,
        channel_url=str(channel_url) if channel_url else None,
    )


def listing_from_ytdlp_json(raw: dict[str, Any], *, url: str, kind: UrlKind) -> PlaylistListing:
    fallback = {
        "channel": raw.get("channel") or raw.get("uploader"),
        "channel_id": raw.get("channel_id") or raw.get("uploader_id") or raw.get("id"),
        "channel_url": raw.get("channel_url") or raw.get("uploader_url") or raw.get("webpage_url"),
    }
    entries_raw = raw.get("entries")
    entries: list[PlaylistEntry] = []
    if isinstance(entries_raw, list):
        for item in entries_raw:
            if not isinstance(item, dict):
                continue
            parsed = _entry_from_raw(item, fallback_channel=fallback)
            if parsed is not None:
                entries.append(parsed)
    list_id = str(raw.get("id") or "") or None
    title = raw.get("title") if isinstance(raw.get("title"), str) else None
    channel = str(fallback["channel"]) if fallback.get("channel") else None
    channel_id = str(fallback["channel_id"]) if fallback.get("channel_id") else None
    channel_url = str(fallback["channel_url"]) if fallback.get("channel_url") else None
    if kind == "channel" and channel_id is None and list_id:
        channel_id = list_id
    return PlaylistListing(
        kind=kind,
        list_id=list_id,
        title=title,
        url=str(raw.get("webpage_url") or url),
        channel=channel,
        channel_id=channel_id,
        channel_url=channel_url,
        entries=tuple(entries),
    )


def summarize_ytdlp_output(stderr: str, *, max_len: int = 1200) -> str:
    """Prefer ERROR lines so UI/DB are not filled with repeated WARNINGs."""
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.upper().startswith("ERROR:")]
    if errors:
        text = "\n".join(errors)
    else:
        text = stderr.strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _subtitle_only_failure(stderr: str) -> bool:
    errors = [ln.strip() for ln in stderr.splitlines() if ln.strip().upper().startswith("ERROR:")]
    if not errors:
        return False
    return all("subtitle" in ln.lower() for ln in errors)


def _classify_ytdlp_error(stderr: str, returncode: int) -> Exception:
    text = stderr.lower()
    summary = summarize_ytdlp_output(stderr)
    if any(
        needle in text
        for needle in (
            "sign in",
            "login required",
            "cookies",
            "confirm your age",
            "members-only",
            "private video",
        )
    ):
        return AuthConfigError(
            "Authentication or cookies required (or cookies expired). "
            "Set LONES_VDL_YTDLP_COOKIES_FILE to a Netscape cookies.txt you exported."
        )
    if any(
        needle in text
        for needle in (
            "http error 429",
            "too many requests",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "network is unreachable",
            "connection reset",
        )
    ):
        return TransientDownloadError(summary or f"yt-dlp failed ({returncode})")
    if any(
        needle in text
        for needle in (
            "video unavailable",
            "has been removed",
            "is not available",
            "copyright",
            "violating",
            "no video formats",
        )
    ):
        return PermanentDownloadError(summary or f"yt-dlp failed ({returncode})")
    return PermanentDownloadError(summary or f"yt-dlp failed ({returncode})")


class YtdlpCliAdapter:
    """Invokes the yt-dlp executable on PATH (or configured path)."""

    def __init__(
        self,
        *,
        executable: str = "yt-dlp",
        cookies_file: Path | None = None,
    ) -> None:
        self.executable = executable
        self.cookies_file = cookies_file

    def _exe(self) -> str:
        return shutil.which(self.executable) or self.executable

    def _cookies_args(self) -> list[str]:
        if self.cookies_file is None:
            return []
        return ["--cookies", str(self.cookies_file)]

    def _base_cmd(self) -> list[str]:
        return [self._exe(), "--no-playlist", "--newline", *self._cookies_args()]

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise PermanentDownloadError(
                f"yt-dlp executable not found ({self.executable}). Install yt-dlp on PATH."
            ) from exc

    def _version(self) -> str | None:
        exe = shutil.which(self.executable) or self.executable
        result = self._run([exe, "--version"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def extract_info(self, url: str) -> VideoInfo:
        cmd = [
            *self._base_cmd(),
            "--dump-single-json",
            "--skip-download",
            url,
        ]
        result = self._run(cmd)
        if result.returncode != 0:
            raise _classify_ytdlp_error(result.stderr or result.stdout, result.returncode)
        raw = json.loads(result.stdout)
        video_id = str(raw.get("id") or "")
        if not video_id:
            raise PermanentDownloadError("yt-dlp returned metadata without an id")
        return VideoInfo(
            platform="youtube",
            video_id=video_id,
            url=str(raw.get("webpage_url") or url),
            title=raw.get("title"),
            raw=raw,
        )

    def list_entries(self, url: str) -> PlaylistListing:
        kind = classify_youtube_url(url)
        if kind == "video":
            raise PermanentDownloadError("list_entries requires a playlist or channel URL")
        # Prefer uploads tab for channel handles when not already on a tab.
        list_url = url
        if kind == "channel" and re.search(r"youtube\.com/@[\w.-]+/?$", url, re.I):
            list_url = url.rstrip("/") + "/videos"
        cmd = [
            self._exe(),
            "--newline",
            *self._cookies_args(),
            "--flat-playlist",
            "--skip-download",
            "--dump-single-json",
            list_url,
        ]
        result = self._run(cmd)
        if result.returncode != 0:
            raise _classify_ytdlp_error(result.stderr or result.stdout, result.returncode)
        raw = json.loads(result.stdout)
        if not isinstance(raw, dict):
            raise PermanentDownloadError("yt-dlp playlist metadata was not an object")
        return listing_from_ytdlp_json(raw, url=list_url, kind=kind)

    def extract_channel_info(self, channel_url: str) -> dict[str, Any]:
        # Channel pages are playlists; skip videos, keep channel thumbnails.
        cmd = [
            self._exe(),
            "--newline",
            *self._cookies_args(),
            "--skip-download",
            "--playlist-items",
            "0",
            "--dump-single-json",
            channel_url,
        ]
        result = self._run(cmd)
        if result.returncode != 0:
            raise _classify_ytdlp_error(result.stderr or result.stdout, result.returncode)
        raw = json.loads(result.stdout)
        if not isinstance(raw, dict):
            raise PermanentDownloadError("yt-dlp channel metadata was not an object")
        return raw

    def download_channel_avatar(self, channel_url: str, *, dest_dir: Path) -> Path | None:
        from lones_vdl.channel_avatars import pick_avatar_url

        raw = self.extract_channel_info(channel_url)
        avatar_url = pick_avatar_url(raw)
        if not avatar_url:
            return None
        path = urlparse(avatar_url).path
        suffix = Path(path).suffix.lower()
        ext = suffix.lstrip(".") if suffix in {".jpg", ".jpeg", ".png", ".webp"} else "jpg"
        dest = dest_dir / f"avatar.{ext}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            avatar_url,
            headers={"User-Agent": "Lones-VDL/0.1 (channel avatar)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.info("Avatar HTTP fetch failed: %s", exc)
            return None
        if not data:
            return None
        dest.write_bytes(data)
        return dest

    def _media_files(self, output_dir: Path) -> list[Path]:
        return [
            p
            for p in output_dir.iterdir()
            if p.is_file()
            and p.name.startswith("media.")
            and p.suffix.lower() not in {".json", ".jpg", ".webp", ".png", ".vtt", ".srt"}
        ]

    def _fetch_subtitles_best_effort(self, url: str, *, output_dir: Path) -> None:
        """Second pass: English subs only. Never fail the archive on subtitle 429s."""
        outtmpl = str(output_dir / "media.%(ext)s")
        cmd = [
            *self._base_cmd(),
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en",
            "--convert-subs",
            "srt",
            "--sleep-subtitles",
            "3",
            "--output",
            outtmpl,
            url,
        ]
        result = self._run(cmd)
        if result.returncode != 0:
            stderr = result.stderr or result.stdout or ""
            logger.warning(
                "Subtitle pass skipped/failed (archive kept): %s",
                summarize_ytdlp_output(stderr, max_len=300),
            )

    def download(
        self,
        url: str,
        *,
        output_dir: Path,
        quality_preference: str,
    ) -> DownloadResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        outtmpl = str(output_dir / "media.%(ext)s")
        fmt = quality_preference if quality_preference != "best" else "bv*+ba/b"
        # Phase 1: media + metadata only. Subtitle rate-limits must not block archival.
        cmd = [
            *self._base_cmd(),
            "--format",
            fmt,
            "--merge-output-format",
            "mkv",
            "--write-info-json",
            "--write-thumbnail",
            "--convert-thumbnails",
            "jpg",
            "--sleep-requests",
            "1",
            "--output",
            outtmpl,
            url,
        ]
        result = self._run(cmd)
        stderr = result.stderr or result.stdout or ""
        if result.returncode != 0:
            raise _classify_ytdlp_error(stderr, result.returncode)

        info_json_files = sorted(output_dir.glob("*.info.json"))
        if info_json_files:
            raw = json.loads(info_json_files[0].read_text(encoding="utf-8"))
            info = VideoInfo(
                platform="youtube",
                video_id=str(raw.get("id") or ""),
                url=str(raw.get("webpage_url") or url),
                title=raw.get("title"),
                raw=raw,
            )
            if not info.video_id:
                raise PermanentDownloadError("yt-dlp info json missing id")
        else:
            info = self.extract_info(url)

        media_candidates = self._media_files(output_dir)
        if not media_candidates:
            raise PermanentDownloadError("yt-dlp finished but no media file was found")
        media_path = media_candidates[0]

        # Phase 2: best-effort English captions (manual + auto). Failures are ignored.
        self._fetch_subtitles_best_effort(url, output_dir=output_dir)

        thumbnails = [
            p
            for p in output_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".jpg", ".webp", ".png"}
        ]
        subtitles = [
            p for p in output_dir.iterdir() if p.is_file() and p.suffix.lower() in {".vtt", ".srt"}
        ]

        return DownloadResult(
            info=info,
            media_path=media_path,
            thumbnail_paths=thumbnails,
            subtitle_paths=subtitles,
            ytdlp_version=self._version(),
        )
