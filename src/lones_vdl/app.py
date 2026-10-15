"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status

from lones_vdl import __version__
from lones_vdl.auth import make_require_api_token
from lones_vdl.config import Settings, get_settings
from lones_vdl.db import Database, JobRow, VideoRow
from lones_vdl.download.service import ArchiveService
from lones_vdl.errors import DuplicateArchiveError
from lones_vdl.platform.ytdlp import YtdlpAdapter, YtdlpCliAdapter
from lones_vdl.schemas import EnqueueRequest, JobResponse, VideoResponse


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


def _video_response(video: VideoRow) -> VideoResponse:
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
    )


def create_app(
    settings: Settings | None = None,
    *,
    adapter: YtdlpAdapter | None = None,
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

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

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
    def list_videos(limit: int = 50) -> list[VideoResponse]:
        return [_video_response(v) for v in service.list_videos(limit=limit)]

    @app.get(
        "/api/videos/{platform}/{platform_video_id}",
        response_model=VideoResponse,
        dependencies=[Depends(require_token)],
    )
    def get_video(platform: str, platform_video_id: str) -> VideoResponse:
        video = service.get_video(platform, platform_video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="Video not found")
        return _video_response(video)

    return app
