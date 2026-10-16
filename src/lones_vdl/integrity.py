"""Archive integrity: checksum verify and sidecar rescan/import."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from lones_vdl.db import Database, utc_now_iso
from lones_vdl.metadata_fields import extract_browse_fields
from lones_vdl.storage import (
    ItemPaths,
    find_media_file,
    item_paths,
    relpath_under,
    sha256_file,
)

VerifyStatus = Literal[
    "ok",
    "missing_media",
    "missing_checksums",
    "checksum_mismatch",
    "missing_on_disk",
    "not_indexed",
    "unreadable",
]


@dataclass
class VerifyItem:
    platform: str
    platform_video_id: str
    status: VerifyStatus
    detail: str
    expected_sha256: str | None = None
    actual_sha256: str | None = None


@dataclass
class VerifyReport:
    checked: int = 0
    ok: int = 0
    issues: list[VerifyItem] = field(default_factory=list)

    def add(self, item: VerifyItem) -> None:
        self.checked += 1
        if item.status == "ok":
            self.ok += 1
        else:
            self.issues.append(item)


@dataclass
class RescanItem:
    platform: str
    platform_video_id: str
    action: Literal["imported", "updated", "skipped", "error"]
    detail: str


@dataclass
class RescanReport:
    scanned: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    missing_from_disk: list[str] = field(default_factory=list)
    items: list[RescanItem] = field(default_factory=list)


def iter_archive_items(archive_root: Path) -> list[ItemPaths]:
    """Discover completed archive item directories under the archive root."""
    if not archive_root.is_dir():
        return []
    found: list[ItemPaths] = []
    for platform_dir in sorted(archive_root.iterdir()):
        if not platform_dir.is_dir():
            continue
        name = platform_dir.name
        if name.startswith(".") or name in {"lost+found"}:
            continue
        for item_dir in sorted(platform_dir.iterdir()):
            if not item_dir.is_dir():
                continue
            if item_dir.name.endswith(".partial"):
                continue
            found.append(item_paths(archive_root, name, item_dir.name))
    return found


def _load_expected_checksum(paths: ItemPaths, media_name: str) -> str | None:
    if not paths.checksums_path.is_file():
        return None
    try:
        payload = json.loads(paths.checksums_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    files = payload.get("files") or {}
    value = files.get(media_name)
    return str(value) if value else None


def verify_video_on_disk(paths: ItemPaths) -> VerifyItem:
    media = find_media_file(paths.final_dir)
    if media is None:
        return VerifyItem(
            platform=paths.platform,
            platform_video_id=paths.video_id,
            status="missing_media",
            detail="No media.* file in item directory",
        )
    if not paths.checksums_path.is_file():
        return VerifyItem(
            platform=paths.platform,
            platform_video_id=paths.video_id,
            status="missing_checksums",
            detail="checksums.json missing",
        )
    expected = _load_expected_checksum(paths, media.name)
    if not expected:
        return VerifyItem(
            platform=paths.platform,
            platform_video_id=paths.video_id,
            status="missing_checksums",
            detail=f"No checksum entry for {media.name}",
        )
    try:
        actual = sha256_file(media)
    except OSError as exc:
        return VerifyItem(
            platform=paths.platform,
            platform_video_id=paths.video_id,
            status="unreadable",
            detail=str(exc),
            expected_sha256=expected,
        )
    if actual.lower() != expected.lower():
        return VerifyItem(
            platform=paths.platform,
            platform_video_id=paths.video_id,
            status="checksum_mismatch",
            detail="SHA-256 does not match checksums.json",
            expected_sha256=expected,
            actual_sha256=actual,
        )
    return VerifyItem(
        platform=paths.platform,
        platform_video_id=paths.video_id,
        status="ok",
        detail="Checksum matches",
        expected_sha256=expected,
        actual_sha256=actual,
    )


def verify_archive(db: Database, archive_root: Path) -> VerifyReport:
    """Verify DB-indexed items; flag missing dirs and unindexed on-disk items."""
    report = VerifyReport()
    indexed: set[tuple[str, str]] = set()

    for video in db.list_all_videos():
        indexed.add((video.platform, video.platform_video_id))
        paths = item_paths(archive_root, video.platform, video.platform_video_id)
        if not paths.final_dir.is_dir():
            report.add(
                VerifyItem(
                    platform=video.platform,
                    platform_video_id=video.platform_video_id,
                    status="missing_on_disk",
                    detail="DB row exists but archive directory is missing",
                    expected_sha256=video.checksum_sha256,
                )
            )
            continue
        report.add(verify_video_on_disk(paths))

    for paths in iter_archive_items(archive_root):
        if (paths.platform, paths.video_id) in indexed:
            continue
        if not paths.metadata_path.is_file() and find_media_file(paths.final_dir) is None:
            continue
        disk = verify_video_on_disk(paths)
        if disk.status == "ok":
            report.add(
                VerifyItem(
                    platform=paths.platform,
                    platform_video_id=paths.video_id,
                    status="not_indexed",
                    detail="On disk and checksum OK, but not in database — run rescan",
                    expected_sha256=disk.expected_sha256,
                    actual_sha256=disk.actual_sha256,
                )
            )
        else:
            report.add(
                VerifyItem(
                    platform=paths.platform,
                    platform_video_id=paths.video_id,
                    status=disk.status,
                    detail=f"Not indexed; {disk.detail}",
                    expected_sha256=disk.expected_sha256,
                    actual_sha256=disk.actual_sha256,
                )
            )

    return report


def _sidecar_fields(paths: ItemPaths) -> dict[str, Any]:
    source: dict[str, Any] = {}
    archive: dict[str, Any] = {}
    if paths.metadata_path.is_file():
        payload = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
        source = payload.get("source") or {}
        archive = payload.get("archive") or {}
    media = find_media_file(paths.final_dir)
    if media is None:
        raise FileNotFoundError("media file missing")
    checksum = _load_expected_checksum(paths, media.name)
    if checksum is None:
        checksum = sha256_file(media)
    fallback_url = archive.get("original_url") or (
        f"https://www.youtube.com/watch?v={paths.video_id}" if paths.platform == "youtube" else None
    )
    browse = extract_browse_fields(source, fallback_url=fallback_url)
    archived_at = archive.get("downloaded_at") or utc_now_iso()
    metadata_relpath = (
        relpath_under(paths.archive_root, paths.metadata_path)
        if paths.metadata_path.is_file()
        else relpath_under(paths.archive_root, media)
    )
    return {
        "title": browse.title,
        "url": browse.url or str(fallback_url or paths.video_id),
        "media_relpath": relpath_under(paths.archive_root, media),
        "metadata_relpath": metadata_relpath,
        "checksum_sha256": checksum,
        "archived_at": str(archived_at),
        "channel": browse.channel,
        "channel_id": browse.channel_id,
        "upload_date": browse.upload_date,
        "metadata_incomplete": browse.incomplete,
        "metadata_gaps": browse.gaps,
    }


def rescan_archive(db: Database, archive_root: Path) -> RescanReport:
    """Import/update DB rows from on-disk sidecars and media."""
    report = RescanReport()
    on_disk: set[tuple[str, str]] = set()

    for paths in iter_archive_items(archive_root):
        on_disk.add((paths.platform, paths.video_id))
        report.scanned += 1
        if not paths.metadata_path.is_file() and find_media_file(paths.final_dir) is None:
            report.skipped += 1
            report.items.append(
                RescanItem(
                    platform=paths.platform,
                    platform_video_id=paths.video_id,
                    action="skipped",
                    detail="Empty or incomplete item directory",
                )
            )
            continue
        try:
            fields = _sidecar_fields(paths)
            _video, action = db.upsert_video(
                platform=paths.platform,
                platform_video_id=paths.video_id,
                title=fields["title"],
                url=fields["url"],
                media_relpath=fields["media_relpath"],
                metadata_relpath=fields["metadata_relpath"],
                checksum_sha256=fields["checksum_sha256"],
                archived_at=fields["archived_at"],
                channel=fields["channel"],
                channel_id=fields["channel_id"],
                upload_date=fields["upload_date"],
                metadata_incomplete=fields["metadata_incomplete"],
                metadata_gaps=fields["metadata_gaps"],
            )
            if action == "imported":
                report.imported += 1
            else:
                report.updated += 1
            report.items.append(
                RescanItem(
                    platform=paths.platform,
                    platform_video_id=paths.video_id,
                    action=action,  # type: ignore[arg-type]
                    detail="Indexed from disk",
                )
            )
        except Exception as exc:  # noqa: BLE001 — per-item boundary
            report.errors += 1
            report.items.append(
                RescanItem(
                    platform=paths.platform,
                    platform_video_id=paths.video_id,
                    action="error",
                    detail=str(exc),
                )
            )

    for video in db.list_all_videos():
        if (video.platform, video.platform_video_id) not in on_disk:
            report.missing_from_disk.append(f"{video.platform}/{video.platform_video_id}")

    return report
