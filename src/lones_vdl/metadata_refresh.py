"""Refresh missing source metadata via yt-dlp and merge into sidecars/DB."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lones_vdl.channel_avatars import channel_url_from_source, ensure_channel_avatar
from lones_vdl.db import Database, VideoRow
from lones_vdl.errors import LonesVdlError
from lones_vdl.metadata_fields import extract_browse_fields
from lones_vdl.platform.ytdlp import YtdlpAdapter
from lones_vdl.storage import item_paths, write_sidecar


@dataclass(frozen=True)
class RefreshResult:
    platform: str
    platform_video_id: str
    status: str
    detail: str
    gaps: tuple[str, ...]


def refresh_video_metadata(
    *,
    db: Database,
    archive_root: Path,
    adapter: YtdlpAdapter,
    video: VideoRow,
) -> RefreshResult:
    """Fetch fresh metadata for one video; update sidecar + DB browse fields."""
    paths = item_paths(archive_root, video.platform, video.platform_video_id)
    source: dict = {}
    archive: dict = {}
    if paths.metadata_path.is_file():
        payload = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
        source = dict(payload.get("source") or {})
        archive = dict(payload.get("archive") or {})

    url = video.url or archive.get("original_url")
    if not url:
        return RefreshResult(
            platform=video.platform,
            platform_video_id=video.platform_video_id,
            status="failed",
            detail="No URL available for metadata refresh",
            gaps=video.metadata_gaps,
        )

    try:
        info = adapter.extract_info(str(url))
    except LonesVdlError as exc:
        # Keep existing source; mark incomplete with archive date fallback already in browse sort.
        browse = extract_browse_fields(source, fallback_url=str(url))
        db.upsert_video(
            platform=video.platform,
            platform_video_id=video.platform_video_id,
            title=browse.title or video.title,
            url=browse.url or video.url,
            media_relpath=video.media_relpath,
            metadata_relpath=video.metadata_relpath,
            checksum_sha256=video.checksum_sha256,
            archived_at=video.archived_at,
            channel=browse.channel or video.channel,
            channel_id=browse.channel_id or video.channel_id,
            upload_date=browse.upload_date or video.upload_date,
            metadata_incomplete=True,
            metadata_gaps=tuple(dict.fromkeys([*browse.gaps, "refresh_failed"])),
            content_kind=video.content_kind,
        )
        return RefreshResult(
            platform=video.platform,
            platform_video_id=video.platform_video_id,
            status="failed",
            detail=str(exc),
            gaps=browse.gaps,
        )

    from lones_vdl.metadata_fields import source_snapshot

    refreshed = source_snapshot(info.raw)
    source.update(refreshed)
    browse = extract_browse_fields(source, fallback_url=info.url)
    if paths.final_dir.is_dir():
        write_sidecar(paths, source=source, archive=archive)

    if browse.channel_id:
        ensure_channel_avatar(
            archive_root=archive_root,
            platform=video.platform,
            channel_id=browse.channel_id,
            channel_url=channel_url_from_source(source),
            adapter=adapter,
        )
    db.upsert_video(
        platform=video.platform,
        platform_video_id=video.platform_video_id,
        title=browse.title or video.title,
        url=browse.url or video.url,
        media_relpath=video.media_relpath,
        metadata_relpath=video.metadata_relpath,
        checksum_sha256=video.checksum_sha256,
        archived_at=video.archived_at,
        channel=browse.channel,
        channel_id=browse.channel_id,
        upload_date=browse.upload_date,
        metadata_incomplete=browse.incomplete,
        metadata_gaps=browse.gaps,
        content_kind=video.content_kind,
    )
    return RefreshResult(
        platform=video.platform,
        platform_video_id=video.platform_video_id,
        status="ok" if not browse.incomplete else "partial",
        detail="Metadata refreshed",
        gaps=browse.gaps,
    )


def refresh_incomplete_metadata(
    *,
    db: Database,
    archive_root: Path,
    adapter: YtdlpAdapter,
    limit: int = 50,
) -> list[RefreshResult]:
    results: list[RefreshResult] = []
    candidates = [v for v in db.list_all_videos() if v.metadata_incomplete or not v.upload_date]
    for video in candidates[:limit]:
        results.append(
            refresh_video_metadata(
                db=db,
                archive_root=archive_root,
                adapter=adapter,
                video=video,
            )
        )
    return results
