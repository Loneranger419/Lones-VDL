"""Archive path layout, checksums, and sidecar metadata."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PLATFORM_YOUTUBE = "youtube"


@dataclass(frozen=True)
class ItemPaths:
    platform: str
    video_id: str
    archive_root: Path

    @property
    def final_dir(self) -> Path:
        return self.archive_root / self.platform / self.video_id

    @property
    def partial_dir(self) -> Path:
        return self.archive_root / self.platform / f"{self.video_id}.partial"

    @property
    def media_glob(self) -> str:
        return "media.*"

    def media_path(self, extension: str) -> Path:
        ext = extension.lstrip(".")
        return self.final_dir / f"media.{ext}"

    @property
    def metadata_path(self) -> Path:
        return self.final_dir / "metadata.json"

    @property
    def checksums_path(self) -> Path:
        return self.final_dir / "checksums.json"

    @property
    def thumbnails_dir(self) -> Path:
        return self.final_dir / "thumbnails"

    @property
    def subtitles_dir(self) -> Path:
        return self.final_dir / "subtitles"


CHANNELS_DIR_NAME = "_channels"


def item_paths(archive_root: Path, platform: str, video_id: str) -> ItemPaths:
    return ItemPaths(platform=platform, video_id=video_id, archive_root=archive_root)


def sanitize_channel_dir_name(channel_id: str) -> str:
    """Filesystem-safe channel id (Windows forbids ':' etc.)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", channel_id.strip())
    return cleaned or "unknown"


@dataclass(frozen=True)
class ChannelPaths:
    platform: str
    channel_id: str
    archive_root: Path

    @property
    def dir(self) -> Path:
        return (
            self.archive_root
            / self.platform
            / CHANNELS_DIR_NAME
            / sanitize_channel_dir_name(self.channel_id)
        )

    @property
    def avatar_glob(self) -> str:
        return "avatar.*"


def channel_paths(archive_root: Path, platform: str, channel_id: str) -> ChannelPaths:
    return ChannelPaths(platform=platform, channel_id=channel_id, archive_root=archive_root)


def find_channel_avatar(paths: ChannelPaths) -> Path | None:
    if not paths.dir.is_dir():
        return None
    matches = sorted(
        p
        for p in paths.dir.glob("avatar.*")
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    return matches[0] if matches else None


def prepare_partial_dir(paths: ItemPaths) -> Path:
    if paths.partial_dir.exists():
        shutil.rmtree(paths.partial_dir)
    paths.partial_dir.mkdir(parents=True, exist_ok=True)
    return paths.partial_dir


def promote_partial(paths: ItemPaths) -> Path:
    """Atomically replace final dir with the completed partial directory."""
    if not paths.partial_dir.exists():
        raise FileNotFoundError(f"partial directory missing: {paths.partial_dir}")
    if paths.final_dir.exists():
        shutil.rmtree(paths.final_dir)
    paths.final_dir.parent.mkdir(parents=True, exist_ok=True)
    paths.partial_dir.rename(paths.final_dir)
    return paths.final_dir


def discard_partial(paths: ItemPaths) -> None:
    if paths.partial_dir.exists():
        shutil.rmtree(paths.partial_dir)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(paths: ItemPaths, media_file: Path) -> str:
    checksum = sha256_file(media_file)
    payload = {
        "algorithm": "sha256",
        "files": {
            media_file.name: checksum,
        },
    }
    paths.checksums_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return checksum


def write_sidecar(
    paths: ItemPaths,
    *,
    source: dict[str, Any],
    archive: dict[str, Any],
) -> Path:
    payload = {
        "source": source,
        "archive": archive,
    }
    paths.metadata_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return paths.metadata_path


def find_media_file(directory: Path) -> Path | None:
    matches = sorted(directory.glob("media.*"))
    matches = [p for p in matches if p.is_file() and p.suffix.lower() != ".json"]
    if not matches:
        return None
    return matches[0]


def relpath_under(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
