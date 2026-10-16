"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lones_vdl import __version__
from lones_vdl.auth import make_require_api_token
from lones_vdl.channel_avatars import (
    channel_has_avatar,
    channel_url_from_source,
    ensure_channel_avatar,
    resolve_channel_avatar_file,
)
from lones_vdl.config import Settings, get_settings
from lones_vdl.cookies import count_cookie_rows, filter_netscape_cookies
from lones_vdl.db import Database, JobRow
from lones_vdl.download.service import ArchiveService
from lones_vdl.errors import DuplicateArchiveError
from lones_vdl.integrity import rescan_archive, verify_archive
from lones_vdl.library import build_detail, load_sidecar, resolve_media_file, to_video_response
from lones_vdl.media import FfmpegMediaProcessor, MediaError, MediaProcessor, find_thumbnail
from lones_vdl.metadata_refresh import refresh_incomplete_metadata, refresh_video_metadata
from lones_vdl.platform.ytdlp import YtdlpAdapter, YtdlpCliAdapter
from lones_vdl.schemas import (
    ChannelResponse,
    CookieFilterResponse,
    EnqueueRequest,
    FavoriteRequest,
    JobResponse,
    PublicConfigResponse,
    RefreshResultResponse,
    RescanItemResponse,
    RescanReportResponse,
    VerifyItemResponse,
    VerifyReportResponse,
    VideoDetailResponse,
    VideoResponse,
)
from lones_vdl.storage import item_paths

QUALITY_PRESETS = [
    "best",
    "bv*+ba/b",
    "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "bestvideo[height<=720]+bestaudio/best[height<=720]",
]


def _job_response(job: JobRow) -> JobResponse:
    return JobResponse(
        id=job.id,
        url=job.url,
        platform=job.platform,
        platform_video_id=job.platform_video_id,
        quality_preference=job.quality_preference,
        status=job.status,
        error_code=job.error_code,
        error_message=job.error_message,
        video_id=job.video_id,
        attempts=job.attempts,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def create_app(
    settings: Settings | None = None,
    *,
    adapter: YtdlpAdapter | None = None,
    media_processor: MediaProcessor | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.archive_root = Path(settings.archive_root)
    settings.database_path = Path(settings.database_path)
    settings.archive_root.mkdir(parents=True, exist_ok=True)

    db = Database(settings.database_path)
    ytdlp: YtdlpAdapter = adapter or YtdlpCliAdapter(
        executable=settings.ytdlp_executable,
        cookies_file=settings.ytdlp_cookies_file,
    )
    service = ArchiveService(
        db=db,
        archive_root=settings.archive_root,
        adapter=ytdlp,
        max_workers=settings.download_concurrency,
        max_attempts=settings.download_max_attempts,
    )
    media = media_processor or FfmpegMediaProcessor()
    require_token = make_require_api_token(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        service.close()
        db.close()

    app = FastAPI(
        title="Lones-VDL",
        version=__version__,
        description="YouTube and Twitch video archival service",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.service = service
    app.state.media = media

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get(
        "/api/config",
        response_model=PublicConfigResponse,
        dependencies=[Depends(require_token)],
    )
    def public_config() -> PublicConfigResponse:
        cookies = settings.ytdlp_cookies_file
        configured = bool(cookies and Path(cookies).is_file())
        return PublicConfigResponse(
            default_quality=settings.default_quality,
            archive_root=str(settings.archive_root.resolve()),
            download_concurrency=settings.download_concurrency,
            download_max_attempts=settings.download_max_attempts,
            cookies_configured=configured,
            cookie_platforms=settings.cookie_platform_list(),
            cookie_count=count_cookie_rows(Path(cookies)) if configured and cookies else None,
            quality_presets=QUALITY_PRESETS,
        )

    @app.post(
        "/api/cookies/filter",
        response_model=CookieFilterResponse,
        dependencies=[Depends(require_token)],
    )
    def filter_cookies() -> CookieFilterResponse:
        """Rewrite the configured cookies file to archive-relevant domains only."""
        cookies = settings.ytdlp_cookies_file
        if cookies is None:
            raise HTTPException(
                status_code=400,
                detail="LONES_VDL_YTDLP_COOKIES_FILE is not configured",
            )
        path = Path(cookies)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"Cookies file not found: {path}")
        try:
            result = filter_netscape_cookies(
                path,
                platforms=settings.cookie_platform_list(),
                write_backup=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return CookieFilterResponse(
            platforms=result.platforms,
            domains_allowed=result.domains_allowed,
            cookies_before=result.cookies_before,
            cookies_after=result.cookies_after,
            cookies_removed=result.cookies_removed,
            lines_before=result.lines_before,
            lines_after=result.lines_after,
            backup_path=result.backup_path,
        )

    @app.post(
        "/api/integrity/verify",
        response_model=VerifyReportResponse,
        dependencies=[Depends(require_token)],
    )
    def integrity_verify() -> VerifyReportResponse:
        report = verify_archive(db, settings.archive_root)
        return VerifyReportResponse(
            checked=report.checked,
            ok=report.ok,
            issue_count=len(report.issues),
            issues=[
                VerifyItemResponse(
                    platform=i.platform,
                    platform_video_id=i.platform_video_id,
                    status=i.status,
                    detail=i.detail,
                    expected_sha256=i.expected_sha256,
                    actual_sha256=i.actual_sha256,
                )
                for i in report.issues
            ],
        )

    @app.post(
        "/api/integrity/rescan",
        response_model=RescanReportResponse,
        dependencies=[Depends(require_token)],
    )
    def integrity_rescan() -> RescanReportResponse:
        report = rescan_archive(db, settings.archive_root)
        return RescanReportResponse(
            scanned=report.scanned,
            imported=report.imported,
            updated=report.updated,
            skipped=report.skipped,
            errors=report.errors,
            missing_from_disk=report.missing_from_disk,
            items=[
                RescanItemResponse(
                    platform=i.platform,
                    platform_video_id=i.platform_video_id,
                    action=i.action,
                    detail=i.detail,
                )
                for i in report.items
            ],
        )

    @app.post(
        "/api/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    def enqueue_job(body: EnqueueRequest) -> JobResponse:
        try:
            job = service.enqueue(
                body.url,
                quality_preference=body.quality_preference or settings.default_quality,
            )
        except DuplicateArchiveError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "detail": str(exc),
                    "code": exc.code,
                    "platform_video_id": exc.platform_video_id,
                },
            ) from exc
        return _job_response(job)

    @app.get(
        "/api/jobs",
        response_model=list[JobResponse],
        dependencies=[Depends(require_token)],
    )
    def list_jobs(limit: int = 50) -> list[JobResponse]:
        return [_job_response(j) for j in service.list_jobs(limit=limit)]

    @app.get(
        "/api/jobs/{job_id}",
        response_model=JobResponse,
        dependencies=[Depends(require_token)],
    )
    def get_job(job_id: str) -> JobResponse:
        job = service.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _job_response(job)

    @app.get(
        "/api/videos",
        response_model=list[VideoResponse],
        dependencies=[Depends(require_token)],
    )
    def list_videos(
        limit: int = 100,
        q: str | None = None,
        channel_id: Annotated[list[str] | None, Query()] = None,
        sort: str = "upload_date",
        order: str = "desc",
        incomplete_only: bool = False,
    ) -> list[VideoResponse]:
        videos = service.list_videos(
            limit=limit,
            q=q,
            channel_ids=channel_id,
            sort=sort,
            order=order,
            incomplete_only=incomplete_only,
        )
        return [to_video_response(settings.archive_root, v) for v in videos]

    @app.get(
        "/api/channels",
        response_model=list[ChannelResponse],
        dependencies=[Depends(require_token)],
    )
    def list_channels(platform: str | None = None) -> list[ChannelResponse]:
        return [
            ChannelResponse(
                platform=c.platform,
                channel_id=c.channel_id,
                channel=c.channel,
                video_count=c.video_count,
                favorited=c.favorited,
                has_thumbnail=channel_has_avatar(settings.archive_root, c.platform, c.channel_id),
            )
            for c in db.list_channels(platform=platform)
        ]

    @app.put(
        "/api/channels/{platform}/{channel_id}/favorite",
        response_model=ChannelResponse,
        dependencies=[Depends(require_token)],
    )
    def set_channel_favorite(
        platform: str,
        channel_id: str,
        body: FavoriteRequest,
    ) -> ChannelResponse:
        db.set_channel_favorite(
            platform=platform,
            channel_id=channel_id,
            channel=body.channel,
            favorited=body.favorited,
        )
        channels = {(c.platform, c.channel_id): c for c in db.list_channels(platform=platform)}
        row = channels.get((platform, channel_id))
        if row is None:
            return ChannelResponse(
                platform=platform,
                channel_id=channel_id,
                channel=body.channel,
                video_count=0,
                favorited=body.favorited,
                has_thumbnail=channel_has_avatar(settings.archive_root, platform, channel_id),
            )
        return ChannelResponse(
            platform=row.platform,
            channel_id=row.channel_id,
            channel=row.channel,
            video_count=row.video_count,
            favorited=row.favorited,
            has_thumbnail=channel_has_avatar(settings.archive_root, row.platform, row.channel_id),
        )

    @app.get(
        "/api/channels/{platform}/{channel_id}/thumbnail",
        dependencies=[Depends(require_token)],
    )
    def get_channel_thumbnail(platform: str, channel_id: str) -> FileResponse:
        avatar = resolve_channel_avatar_file(settings.archive_root, platform, channel_id)
        if avatar is None:
            # Lazy backfill from first archived video's channel_url / metadata refresh path.
            channel_url = None
            for video in db.list_videos(limit=5, channel_ids=[channel_id]):
                if video.platform != platform:
                    continue
                source, _archive = load_sidecar(settings.archive_root, video)
                if source:
                    channel_url = channel_url_from_source(source)
                    if channel_url:
                        break
            if channel_url:
                avatar = ensure_channel_avatar(
                    archive_root=settings.archive_root,
                    platform=platform,
                    channel_id=channel_id,
                    channel_url=channel_url,
                    adapter=ytdlp,
                )
        if avatar is None or not avatar.is_file():
            raise HTTPException(status_code=404, detail="Channel thumbnail not found")
        return FileResponse(avatar)

    @app.get(
        "/api/videos/{platform}/{platform_video_id}",
        response_model=VideoDetailResponse,
        dependencies=[Depends(require_token)],
    )
    def get_video(platform: str, platform_video_id: str) -> VideoDetailResponse:
        video = service.get_video(platform, platform_video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="Video not found")
        try:
            return build_detail(
                archive_root=settings.archive_root,
                video=video,
                processor=media,
                ensure_remux=True,
            )
        except MediaError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get(
        "/api/videos/{platform}/{platform_video_id}/related",
        response_model=list[VideoResponse],
        dependencies=[Depends(require_token)],
    )
    def related_videos(
        platform: str,
        platform_video_id: str,
        limit: int = 12,
    ) -> list[VideoResponse]:
        video = service.get_video(platform, platform_video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="Video not found")
        related = db.list_related(
            platform=platform,
            channel_id=video.channel_id,
            exclude_video_id=platform_video_id,
            limit=limit,
        )
        return [to_video_response(settings.archive_root, v) for v in related]

    @app.post(
        "/api/videos/{platform}/{platform_video_id}/refresh",
        response_model=RefreshResultResponse,
        dependencies=[Depends(require_token)],
    )
    def refresh_one_video(platform: str, platform_video_id: str) -> RefreshResultResponse:
        video = service.get_video(platform, platform_video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="Video not found")
        result = refresh_video_metadata(
            db=db,
            archive_root=settings.archive_root,
            adapter=ytdlp,
            video=video,
        )
        return RefreshResultResponse(
            platform=result.platform,
            platform_video_id=result.platform_video_id,
            status=result.status,
            detail=result.detail,
            gaps=list(result.gaps),
        )

    @app.post(
        "/api/metadata/refresh-incomplete",
        response_model=list[RefreshResultResponse],
        dependencies=[Depends(require_token)],
    )
    def refresh_incomplete(limit: int = 50) -> list[RefreshResultResponse]:
        results = refresh_incomplete_metadata(
            db=db,
            archive_root=settings.archive_root,
            adapter=ytdlp,
            limit=limit,
        )
        return [
            RefreshResultResponse(
                platform=r.platform,
                platform_video_id=r.platform_video_id,
                status=r.status,
                detail=r.detail,
                gaps=list(r.gaps),
            )
            for r in results
        ]

    @app.get(
        "/api/videos/{platform}/{platform_video_id}/thumbnail",
        dependencies=[Depends(require_token)],
    )
    def get_thumbnail(platform: str, platform_video_id: str) -> FileResponse:
        video = service.get_video(platform, platform_video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="Video not found")
        paths = item_paths(settings.archive_root, platform, platform_video_id)
        thumb = find_thumbnail(paths)
        if thumb is None or not thumb.is_file():
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        return FileResponse(thumb)

    @app.get(
        "/api/videos/{platform}/{platform_video_id}/media",
        dependencies=[Depends(require_token)],
    )
    def get_media(
        platform: str,
        platform_video_id: str,
        variant: str = "play",
    ) -> FileResponse:
        video = service.get_video(platform, platform_video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="Video not found")
        media_file = resolve_media_file(settings.archive_root, video)
        if not media_file.is_file():
            raise HTTPException(status_code=404, detail="Media file missing")

        if variant == "original":
            return FileResponse(media_file, filename=media_file.name)

        try:
            detail = build_detail(
                archive_root=settings.archive_root,
                video=video,
                processor=media,
                ensure_remux=True,
            )
        except MediaError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        playback = detail.playback
        assert playback is not None
        if playback.mode == "unavailable" or not playback.play_path:
            raise HTTPException(
                status_code=415,
                detail=playback.reason,
            )
        play_file = (settings.archive_root / playback.play_path).resolve()
        archive_root = settings.archive_root.resolve()
        try:
            play_file.relative_to(archive_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid media path") from exc
        if not play_file.is_file():
            raise HTTPException(status_code=404, detail="Playable derivative missing")
        return FileResponse(play_file, filename=play_file.name)

    # Serve built web UI when present (production / docker).
    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app
