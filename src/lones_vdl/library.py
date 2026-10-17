"""Library browse helpers: metadata, playback planning, file resolution."""

from __future__ import annotations

import json
from pathlib import Path

from lones_vdl.db import VideoRow
from lones_vdl.media import (
    MediaError,
    MediaProcessor,
    PlaybackPlan,
    ensure_playable_derivative,
    find_thumbnail,
    plan_playback,
)
from lones_vdl.schemas import PlaybackInfo, VideoDetailResponse, VideoResponse
from lones_vdl.storage import item_paths, relpath_under


def video_has_thumbnail(archive_root: Path, video: VideoRow) -> bool:
    paths = item_paths(archive_root, video.platform, video.platform_video_id)
    return find_thumbnail(paths) is not None


def to_video_response(archive_root: Path, video: VideoRow) -> VideoResponse:
    return VideoResponse(
        id=video.id,
        platform=video.platform,
        platform_video_id=video.platform_video_id,
        title=video.title,
        url=video.url,
        media_relpath=video.media_relpath,
        metadata_relpath=video.metadata_relpath,
        checksum_sha256=video.checksum_sha256,
        archived_at=video.archived_at,
        has_thumbnail=video_has_thumbnail(archive_root, video),
        channel=video.channel,
        channel_id=video.channel_id,
        upload_date=video.upload_date,
        metadata_incomplete=video.metadata_incomplete,
        metadata_gaps=list(video.metadata_gaps),
        content_kind=video.content_kind or "video",
    )


def load_sidecar(archive_root: Path, video: VideoRow) -> tuple[dict | None, dict | None]:
    meta_path = archive_root / video.metadata_relpath
    if not meta_path.is_file():
        return None, None
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return payload.get("source"), payload.get("archive")


def resolve_media_file(archive_root: Path, video: VideoRow) -> Path:
    return (archive_root / video.media_relpath).resolve()


def build_detail(
    *,
    archive_root: Path,
    video: VideoRow,
    processor: MediaProcessor,
    ensure_remux: bool = True,
) -> VideoDetailResponse:
    source, archive = load_sidecar(archive_root, video)
    media_file = resolve_media_file(archive_root, video)
    paths = item_paths(archive_root, video.platform, video.platform_video_id)
    plan: PlaybackPlan
    if media_file.is_file() and ensure_remux:
        try:
            plan = ensure_playable_derivative(
                paths=paths,
                media_file=media_file,
                processor=processor,
            )
        except MediaError as exc:
            probe_plan = plan_playback(processor.probe(media_file), source_path=media_file)
            plan = PlaybackPlan(
                mode="unavailable",
                container=None,
                reason=f"Remux failed: {exc}",
                video_codec=probe_plan.video_codec,
                audio_codec=probe_plan.audio_codec,
            )
    elif media_file.is_file():
        plan = plan_playback(processor.probe(media_file), source_path=media_file)
    else:
        plan = PlaybackPlan(
            mode="unavailable",
            container=None,
            reason="Media file missing on disk",
            video_codec=None,
            audio_codec=None,
        )

    play_path = None
    if plan.mode == "original":
        play_path = video.media_relpath
    elif plan.mode == "remux" and plan.derivative_relpath:
        play_path = relpath_under(archive_root, paths.final_dir / plan.derivative_relpath)

    base = to_video_response(archive_root, video)
    return VideoDetailResponse(
        **base.model_dump(),
        source_metadata=source,
        archive_metadata=archive,
        playback=PlaybackInfo(
            mode=plan.mode,
            container=plan.container,
            reason=plan.reason,
            video_codec=plan.video_codec,
            audio_codec=plan.audio_codec,
            play_path=play_path,
            original_path=video.media_relpath,
        ),
    )
