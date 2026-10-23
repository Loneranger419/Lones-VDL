"""Archive layout on disk. Each item is self-describing: media + metadata.json + checksums.json.

<archive_root>/<platform>/<video_id>/
    media.<ext>  info.json  thumbnail.jpg  subtitles/<lang>.vtt
    metadata.json  checksums.json
<archive_root>/<platform>/_channels/<channel_id>/avatar.jpg, banner.jpg
<archive_root>/.partial/<job_id>/      in-progress downloads (same filesystem → atomic move)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SIDECAR_SCHEMA_VERSION = 1
METADATA_FILE = "metadata.json"
CHECKSUMS_FILE = "checksums.json"
INFO_FILE = "info.json"
CHANNELS_DIR = "_channels"

_MEDIA_EXTS = {".webm", ".mp4", ".mkv", ".m4a", ".mp3", ".opus", ".ogg", ".mov", ".flv"}
_THUMB_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_INCOMPLETE = re.compile(r"\.(part|ytdl|temp|tmp)$|\.part-Frag\d+|\.f\d+[\w-]*\.\w+$")


class ArchiveConflict(Exception):
    pass


def video_dir(root: Path, platform: str, video_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", video_id):
        raise ValueError(f"unsafe video id: {video_id!r}")
    return root / platform / video_id


def channel_dir(root: Path, platform: str, channel_id: str) -> Path:
    """Channel artwork. The leading underscore keeps it apart from video id directories."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", channel_id):
        raise ValueError(f"unsafe channel id: {channel_id!r}")
    return root / platform / CHANNELS_DIR / channel_id


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def resolve_inside(root: Path, rel: str) -> Path:
    """Resolve a DB-stored relative path, refusing anything that escapes the archive root."""
    base = root.resolve()
    path = (base / rel).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"path escapes the archive root: {rel!r}")
    return path


def partial_dir(partial_root: Path, job_id: int) -> Path:
    path = partial_root / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Outputs:
    media: Path
    info: Path | None = None
    thumbnail: Path | None = None
    subtitles: list[Path] = field(default_factory=list)


def discover_outputs(workdir: Path) -> Outputs:
    """Find what yt-dlp produced, tolerant of its naming details."""
    media = [
        p
        for p in workdir.glob("media.*")
        if p.is_file() and p.suffix.lower() in _MEDIA_EXTS and not _INCOMPLETE.search(p.name)
    ]
    if not media:
        raise FileNotFoundError("yt-dlp finished but produced no media file")
    info = next(iter(sorted(workdir.glob("*.info.json"))), None)
    thumbs = [p for p in workdir.glob("thumbnail*") if p.suffix.lower() in _THUMB_EXTS]
    subtitles = sorted((workdir / "subtitles").glob("*.vtt"))
    return Outputs(
        media=max(media, key=lambda p: p.stat().st_size),
        info=info,
        thumbnail=min(thumbs, key=lambda p: (p.suffix.lower() != ".jpg", p.name), default=None),
        subtitles=subtitles,
    )


def normalize(workdir: Path, outputs: Outputs, *, fallback_info: Path | None = None) -> Outputs:
    """Rename outputs to canonical names and remove everything else from workdir."""
    keep: set[Path] = set()

    def move(src: Path, name: str) -> Path:
        dest = workdir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src != dest:
            os.replace(src, dest)
        keep.add(dest)
        return dest

    media = move(outputs.media, f"media{outputs.media.suffix.lower()}")
    info_src = outputs.info or fallback_info
    info = move(info_src, INFO_FILE) if info_src is not None and info_src.exists() else None
    thumbnail = (
        move(outputs.thumbnail, f"thumbnail{outputs.thumbnail.suffix.lower()}")
        if outputs.thumbnail
        else None
    )
    subtitles = []
    for sub in outputs.subtitles:
        # subs.en.vtt → subtitles/en.vtt
        lang = sub.name.removeprefix("subs.").removesuffix(".vtt") or "und"
        subtitles.append(move(sub, f"subtitles/{lang}.vtt"))

    for path in sorted(workdir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path in keep:
            continue
        if path.is_dir():
            if not any(path.iterdir()):
                path.rmdir()
        else:
            path.unlink()
    return Outputs(media=media, info=info, thumbnail=thumbnail, subtitles=subtitles)


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


def write_sidecar(workdir: Path, metadata: dict[str, Any]) -> None:
    _write_json(workdir / METADATA_FILE, {"schema_version": SIDECAR_SCHEMA_VERSION, **metadata})


def write_checksums(workdir: Path) -> dict[str, str]:
    sums = {
        p.relative_to(workdir).as_posix(): sha256_file(p)
        for p in sorted(workdir.rglob("*"))
        if p.is_file() and p.name != CHECKSUMS_FILE
    }
    _write_json(workdir / CHECKSUMS_FILE, {"algorithm": "sha256", "files": sums})
    return sums


def promote(workdir: Path, dest: Path) -> None:
    """Move a finished item into place. Refuses to overwrite an existing archive item."""
    if dest.exists():
        raise ArchiveConflict(f"{dest} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(workdir, dest)


def remove_partial(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
