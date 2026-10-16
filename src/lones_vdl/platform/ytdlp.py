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
from typing import Any, Protocol
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


class YtdlpAdapter(Protocol):
    def extract_info(self, url: str) -> VideoInfo: ...

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


def _classify_ytdlp_error(stderr: str, returncode: int) -> Exception:
    text = stderr.lower()
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
        return TransientDownloadError(stderr.strip() or f"yt-dlp failed ({returncode})")
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
        return PermanentDownloadError(stderr.strip() or f"yt-dlp failed ({returncode})")
    return PermanentDownloadError(stderr.strip() or f"yt-dlp failed ({returncode})")


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
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,en",
            "--output",
            outtmpl,
            url,
        ]
        result = self._run(cmd)
        if result.returncode != 0:
            raise _classify_ytdlp_error(result.stderr or result.stdout, result.returncode)

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

        media_candidates = [
            p
            for p in output_dir.iterdir()
            if p.is_file()
            and p.name.startswith("media.")
            and p.suffix.lower() not in {".json", ".jpg", ".webp", ".png", ".vtt", ".srt"}
        ]
        if not media_candidates:
            raise PermanentDownloadError("yt-dlp finished but no media file was found")
        media_path = media_candidates[0]

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
