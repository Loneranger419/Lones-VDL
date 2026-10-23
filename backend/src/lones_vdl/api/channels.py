"""Channels: details, artwork, and auto-archive ("watch") settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from lones_vdl.api.deps import AuthDep, DbDep, ServicesDep
from lones_vdl.api.videos import archive_file
from lones_vdl.db.models import Channel, Creator, Job, JobKind
from lones_vdl.schemas import ChannelDetail, ChannelUpdate, JobOut
from lones_vdl.services import channels as channel_service
from lones_vdl.services import jobs as job_service
from lones_vdl.services.expand import check_job
from lones_vdl.ytdlp import QUALITIES

router = APIRouter(prefix="/channels", tags=["channels"], dependencies=[AuthDep])


def _get(db, channel_pk: int) -> Channel:
    channel = db.get(Channel, channel_pk)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    return channel


def _detail(channel: Channel, stats: dict[int, tuple[int, int]]) -> ChannelDetail:
    count, size = stats.get(channel.id, (0, 0))
    return ChannelDetail.model_validate(channel).model_copy(
        update={"video_count": count, "total_size": size}
    )


@router.get("", response_model=list[ChannelDetail])
def list_channels(db: DbDep):
    stats = channel_service.video_stats(db)
    channels = db.scalars(select(Channel).order_by(func.lower(Channel.name))).all()
    return [_detail(c, stats) for c in channels]


@router.get("/{channel_pk}", response_model=ChannelDetail)
def get_channel(channel_pk: int, db: DbDep):
    return _detail(_get(db, channel_pk), channel_service.video_stats(db))


@router.patch("/{channel_pk}", response_model=ChannelDetail)
def update_channel(channel_pk: int, body: ChannelUpdate, db: DbDep, services: ServicesDep):
    """Turning watch on lists the channel now: by default existing videos are skipped and
    only later uploads are archived; with backfill=true the back catalogue is queued too."""
    channel = _get(db, channel_pk)
    changes = body.model_dump(exclude_unset=True, exclude={"backfill"})
    if "watch_quality" in changes and changes["watch_quality"] not in (None, *QUALITIES):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown quality")
    if changes.get("creator_id") is not None and db.get(Creator, changes["creator_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown creator")
    turning_on = changes.get("watch_enabled") is True and not channel.watch_enabled
    if "creator_id" in changes:
        channel.creator_pk = changes.pop("creator_id")
    for key, value in changes.items():
        setattr(channel, key, value)
    job = None
    if turning_on and channel_service.active_expand_for_channel(db, channel.id) is None:
        defaults = services.runtime.current
        job = Job(
            kind=JobKind.EXPAND,
            url=channel_service.channel_base_url(channel),
            platform=channel.platform,
            quality=channel.watch_quality or defaults.default_quality,
            title=channel.name,
            priority=job_service.PRIORITY_EXPAND,
            channel_pk=channel.id,
            options={
                "mode": "all" if body.backfill else "baseline",
                "tabs": channel_service.enabled_tabs(channel),
                "child_priority": job_service.PRIORITY_BACKFILL,
            },
            max_attempts=services.settings.download_max_attempts,
        )
        db.add(job)
    db.commit()
    if job is not None:
        services.bus.publish("job", job_service.job_payload(job))
        services.worker.wake()
    return _detail(channel, channel_service.video_stats(db))


@router.post("/{channel_pk}/check", status_code=status.HTTP_201_CREATED, response_model=JobOut)
def check_now(channel_pk: int, db: DbDep, services: ServicesDep):
    """Look for new uploads now (uses the channel's watch tabs; works even if watch is off)."""
    channel = _get(db, channel_pk)
    active = channel_service.active_expand_for_channel(db, channel.id)
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "this channel is already being checked")
    if not channel_service.enabled_tabs(channel):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no tabs selected")
    job = check_job(
        channel,
        quality=services.runtime.current.default_quality,
        max_attempts=services.settings.download_max_attempts,
    )
    job.priority = job_service.PRIORITY_EXPAND
    db.add(job)
    db.commit()
    services.bus.publish("job", job_service.job_payload(job))
    services.worker.wake()
    return job


@router.get("/{channel_pk}/avatar")
def avatar(channel_pk: int, db: DbDep, services: ServicesDep) -> FileResponse:
    channel = _get(db, channel_pk)
    if channel.avatar_file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no avatar")
    return archive_file(services.settings.archive_root, channel.avatar_file)


@router.get("/{channel_pk}/banner")
def banner(channel_pk: int, db: DbDep, services: ServicesDep) -> FileResponse:
    channel = _get(db, channel_pk)
    if channel.banner_file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no banner")
    return archive_file(services.settings.archive_root, channel.banner_file)
