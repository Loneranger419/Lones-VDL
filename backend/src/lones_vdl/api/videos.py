"""Library browsing, playback state, and media files."""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse

from lones_vdl.api.deps import AuthDep, DbDep, ServicesDep
from lones_vdl.db.models import ContentKind, Integrity, Video
from lones_vdl.schemas import (
    JobOut,
    ProgressUpdate,
    RelatedOut,
    VideoDetail,
    VideoOut,
    VideoPage,
    WatchedUpdate,
)
from lones_vdl.services import downloads, library, presets, subtitles
from lones_vdl.services import jobs as job_service
from lones_vdl.storage import archive

router = APIRouter(prefix="/videos", tags=["videos"], dependencies=[AuthDep])

# Browsers need exact types to pick a decoder; mimetypes misses some of these on Windows.
MEDIA_TYPES = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".m4a": "audio/mp4",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".vtt": "text/vtt",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
# Archived files never change in place, but a video can be deleted and re-downloaded.
MEDIA_CACHE = "private, max-age=86400"


def _get(db, video_pk: int) -> Video:
    video = library.get_video(db, video_pk)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "video not found")
    return video


def archive_file(root: Path, rel: str) -> FileResponse:
    """Serve a file under the archive root (Range requests supported)."""
    try:
        path = archive.resolve_inside(root, rel)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found") from exc
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    media_type = MEDIA_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": MEDIA_CACHE},
    )


@router.get("", response_model=VideoPage)
def list_videos(
    db: DbDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    channel: Annotated[int | None, Query()] = None,
    creator: Annotated[int | None, Query()] = None,
    kind: Annotated[ContentKind | None, Query()] = None,
    watch: Annotated[library.WatchFilter | None, Query()] = None,
    integrity: Annotated[Integrity | None, Query()] = None,
    tag: Annotated[list[str] | None, Query(description="has all of these tags")] = None,
    exclude_tag: Annotated[list[str] | None, Query(description="has none of these")] = None,
    preset: Annotated[
        str | None, Query(description="filter preset: an id, 'default', or 'none' (the default)")
    ] = None,
    sort: Annotated[library.Sort, Query()] = "archived_desc",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 48,
):
    chosen = presets.resolve(db, preset)
    params = library.VideoQuery(
        q=q.strip() if q else None,
        channel_pk=channel,
        creator_pk=creator,
        kind=kind,
        watch=watch,
        integrity=integrity,
        tags=tag or [],
        exclude_tags=exclude_tag or [],
        preset_tags=chosen.include if chosen else [],
        preset_exclude_tags=chosen.exclude if chosen else [],
        sort=sort,
        offset=offset,
        limit=limit,
    )
    items, total, hidden = library.query_videos(db, params)
    return VideoPage(
        items=[VideoOut.model_validate(v) for v in items],
        total=total,
        hidden=hidden,
        offset=offset,
        limit=limit,
    )


@router.get("/continue", response_model=list[VideoOut])
def continue_watching(db: DbDep, limit: Annotated[int, Query(ge=1, le=100)] = 12):
    """Started but not finished, most recently watched first."""
    return library.continue_watching(db, limit)


@router.get("/{video_pk}", response_model=VideoDetail)
def get_video(video_pk: int, db: DbDep, services: ServicesDep):
    video = _get(db, video_pk)
    return VideoDetail.model_validate(video).model_copy(
        update={
            "subtitles": library.subtitle_langs(services.settings, video),
            "collection_ids": library.collection_ids(db, video.id),
            "tags": video.tags,
        }
    )


@router.post("/{video_pk}/subtitles", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
def fetch_subtitles(video_pk: int, db: DbDep, services: ServicesDep):
    """Queue a download of this video's subtitles. Archiving skips them by default."""
    video = _get(db, video_pk)
    try:
        job = subtitles.enqueue(db, services.settings, video)
    except downloads.EnqueueError as exc:
        return JSONResponse(
            status_code=exc.status,
            content={"detail": exc.message, "kind": exc.kind, **exc.extra},
        )
    db.commit()
    services.bus.publish("job", job_service.job_payload(job))
    services.worker.wake()
    return job


@router.get("/{video_pk}/related", response_model=RelatedOut)
def related(
    video_pk: int,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
):
    up_next, more = library.related(db, _get(db, video_pk), limit)
    return RelatedOut(
        up_next=VideoOut.model_validate(up_next) if up_next else None,
        more_from_channel=[VideoOut.model_validate(v) for v in more],
    )


@router.put("/{video_pk}/progress", status_code=status.HTTP_204_NO_CONTENT)
def save_progress(video_pk: int, body: ProgressUpdate, db: DbDep) -> None:
    """Called by the player every few seconds and on pause/close."""
    library.set_progress(db, _get(db, video_pk), body.position_seconds)
    db.commit()


@router.put("/{video_pk}/watched", response_model=VideoOut)
def set_watched(video_pk: int, body: WatchedUpdate, db: DbDep):
    video = _get(db, video_pk)
    library.set_watched(db, video, body.watched)
    db.commit()
    return video


@router.delete("/{video_pk}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(
    video_pk: int,
    db: DbDep,
    services: ServicesDep,
    delete_files: Annotated[bool, Query(description="also remove the files from disk")] = True,
) -> None:
    """Channel checks will not queue a deleted video again; adding it by URL still works."""
    directory = library.delete_video(db, services.settings, _get(db, video_pk))
    db.commit()
    services.bus.publish("video.removed", {"id": video_pk})
    if delete_files and directory.exists():
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"removed from the library, but deleting files failed: {exc}",
            ) from exc


@router.get("/{video_pk}/media")
def media(video_pk: int, db: DbDep, services: ServicesDep) -> FileResponse:
    video = _get(db, video_pk)
    return archive_file(services.settings.archive_root, f"{video.directory}/{video.media_file}")


@router.get("/{video_pk}/thumbnail")
def thumbnail(video_pk: int, db: DbDep, services: ServicesDep) -> FileResponse:
    video = _get(db, video_pk)
    if video.thumbnail_file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no thumbnail")
    return archive_file(services.settings.archive_root, f"{video.directory}/{video.thumbnail_file}")


@router.get("/{video_pk}/subtitles/{lang}.vtt")
def subtitle(video_pk: int, lang: str, db: DbDep, services: ServicesDep) -> FileResponse:
    video = _get(db, video_pk)
    if lang not in library.subtitle_langs(services.settings, video):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such subtitle")
    return archive_file(services.settings.archive_root, f"{video.directory}/subtitles/{lang}.vtt")
