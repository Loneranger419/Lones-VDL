"""FFmpeg probe and remux-only browser derivatives."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from lones_vdl.errors import LonesVdlError
from lones_vdl.storage import ItemPaths

BrowserVideo = Literal["h264", "vp8", "vp9", "av1"]
BrowserAudio = Literal["aac", "mp3", "opus", "vorbis"]
PlayContainer = Literal["mp4", "webm"]


class MediaError(LonesVdlError):
    code = "media"


@dataclass(frozen=True)
class StreamInfo:
    codec_type: str
    codec_name: str | None


@dataclass(frozen=True)
class ProbeResult:
    format_name: str | None
    streams: list[StreamInfo]

    @property
    def video_codec(self) -> str | None:
        for stream in self.streams:
            if stream.codec_type == "video" and stream.codec_name:
                return stream.codec_name.lower()
        return None

    @property
    def audio_codec(self) -> str | None:
        for stream in self.streams:
            if stream.codec_type == "audio" and stream.codec_name:
                return stream.codec_name.lower()
        return None


@dataclass(frozen=True)
class PlaybackPlan:
    """How the web UI should attempt playback (original never modified)."""

    mode: Literal["original", "remux", "unavailable"]
    container: PlayContainer | None
    reason: str
    video_codec: str | None
    audio_codec: str | None
    derivative_relpath: str | None = None


def _normalize_video(codec: str | None) -> str | None:
    if codec is None:
        return None
    mapping = {
        "h264": "h264",
        "avc1": "h264",
        "avc": "h264",
        "vp8": "vp8",
        "vp9": "vp9",
        "av1": "av1",
        "libaom-av1": "av1",
    }
    return mapping.get(codec)


def _normalize_audio(codec: str | None) -> str | None:
    if codec is None:
        return None
    mapping = {
        "aac": "aac",
        "mp3": "mp3",
        "opus": "opus",
        "vorbis": "vorbis",
    }
    return mapping.get(codec)


def plan_playback(probe: ProbeResult, *, source_path: Path | None = None) -> PlaybackPlan:
    """Choose remux-only browser strategy; never plan a re-encode."""
    video = _normalize_video(probe.video_codec)
    audio = _normalize_audio(probe.audio_codec)
    # Prefer extension: ffprobe often reports "matroska,webm" for both .mkv and .webm.
    suffix = source_path.suffix.lower() if source_path is not None else ""

    if suffix in {".mp4", ".m4v"} and video in {"h264", "av1"} and audio in {"aac", "mp3"}:
        return PlaybackPlan(
            mode="original",
            container="mp4",
            reason="Original MP4 is browser-playable",
            video_codec=video,
            audio_codec=audio,
        )
    if suffix == ".webm" and video in {"vp8", "vp9", "av1"} and audio in {"opus", "vorbis"}:
        return PlaybackPlan(
            mode="original",
            container="webm",
            reason="Original WebM is browser-playable",
            video_codec=video,
            audio_codec=audio,
        )

    # Remux AV1/VP9/VP8 + Opus/Vorbis → WebM (copy only).
    if video in {"vp8", "vp9", "av1"} and audio in {"opus", "vorbis"}:
        return PlaybackPlan(
            mode="remux",
            container="webm",
            reason="Remux to WebM without re-encoding",
            video_codec=video,
            audio_codec=audio,
            derivative_relpath="derivatives/play.webm",
        )

    # Remux H.264/AV1 + AAC/MP3 → MP4 (copy only).
    if video in {"h264", "av1"} and audio in {"aac", "mp3"}:
        return PlaybackPlan(
            mode="remux",
            container="mp4",
            reason="Remux to MP4 without re-encoding",
            video_codec=video,
            audio_codec=audio,
            derivative_relpath="derivatives/play.mp4",
        )

    return PlaybackPlan(
        mode="unavailable",
        container=None,
        reason=(
            "No remux-only browser path for "
            f"video={probe.video_codec!r} audio={probe.audio_codec!r}; "
            "transcoding is deferred"
        ),
        video_codec=video,
        audio_codec=audio,
    )


class MediaProcessor(Protocol):
    def probe(self, path: Path) -> ProbeResult: ...

    def remux_copy(self, source: Path, destination: Path) -> None: ...


class FfmpegMediaProcessor:
    def __init__(self, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def probe(self, path: Path) -> ProbeResult:
        exe = shutil.which(self.ffprobe) or self.ffprobe
        cmd = [
            exe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise MediaError("ffprobe not found on PATH") from exc
        if result.returncode != 0:
            raise MediaError(result.stderr.strip() or "ffprobe failed")
        payload: dict[str, Any] = json.loads(result.stdout)
        streams = [
            StreamInfo(
                codec_type=str(s.get("codec_type") or ""),
                codec_name=s.get("codec_name"),
            )
            for s in payload.get("streams", [])
        ]
        fmt = payload.get("format", {}).get("format_name")
        return ProbeResult(format_name=fmt, streams=streams)

    def remux_copy(self, source: Path, destination: Path) -> None:
        exe = shutil.which(self.ffmpeg) or self.ffmpeg
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Keep a real container extension so ffmpeg can detect the muxer
        # (e.g. play.partial.webm — not play.webm.partial).
        tmp = destination.with_name(f"{destination.stem}.partial{destination.suffix}")
        fmt = {".webm": "webm", ".mp4": "mp4"}.get(destination.suffix.lower())
        if tmp.exists():
            tmp.unlink()
        cmd = [
            exe,
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
        ]
        if fmt:
            cmd.extend(["-f", fmt])
        cmd.append(str(tmp))
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise MediaError("ffmpeg not found on PATH") from exc
        if result.returncode != 0:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise MediaError(_short_ffmpeg_error(result.stderr) or "ffmpeg remux failed")
        tmp.replace(destination)


def _short_ffmpeg_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    # Skip the long banner; keep the useful trailing diagnostics.
    useful = [line for line in lines if not line.startswith("ffmpeg version")]
    if not useful:
        useful = lines
    return "\n".join(useful[-12:])


def ensure_playable_derivative(
    *,
    paths: ItemPaths,
    media_file: Path,
    processor: MediaProcessor,
) -> PlaybackPlan:
    """Probe original; create remux derivative if needed and possible."""
    probe = processor.probe(media_file)
    plan = plan_playback(probe, source_path=media_file)
    if plan.mode != "remux" or not plan.derivative_relpath:
        return plan

    dest = paths.final_dir / plan.derivative_relpath
    if not dest.exists():
        processor.remux_copy(media_file, dest)
    return plan


def find_thumbnail(paths: ItemPaths) -> Path | None:
    if not paths.thumbnails_dir.exists():
        return None
    for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        matches = sorted(paths.thumbnails_dir.glob(pattern))
        if matches:
            return matches[0]
    return None
