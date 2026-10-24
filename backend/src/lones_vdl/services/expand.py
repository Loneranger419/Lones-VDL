"""List a playlist or channel and queue the videos that are not archived yet.

Expand job options:
    mode           all       queue every new video (playlist, or channel back catalogue)
                   recent    same, limited to the newest entries (scheduled channel checks)
                   baseline  ignore everything listed now; only later uploads get queued
                   meta      only refresh channel details and artwork
    tabs           channel tabs to list: videos, streams, shorts
    quality        quality for the queued downloads
    child_priority priority for the queued downloads
    limit          newest N entries per tab
    watch          set the channel's auto-archive flag (and its tabs) when done
    watch_quality  the channel's auto-archive quality (None = follow the default)
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, TextIO

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import AttemptKind, Channel, ContentKind, Job, JobKind, JobStage
from lones_vdl.platforms import UrlKind, get_platform, parse_url
from lones_vdl.services import accounts as account_service
from lones_vdl.services import channels as channel_service
from lones_vdl.services.jobs import (
    PRIORITY_NEW_UPLOAD,
    PRIORITY_WATCH_CHECK,
    JobReporter,
    open_job_log,
)
from lones_vdl.services.policy import Policy
from lones_vdl.storage import archive
from lones_vdl.ytdlp import CancelToken, ErrorKind, YtdlpError, YtdlpManager, YtdlpRunner
from lones_vdl.ytdlp.errors import MESSAGES

logger = logging.getLogger(__name__)

RECENT_LIMIT = 50
SKIP_LIVE_STATUS = {"is_live", "is_upcoming"}


def check_job(channel: Channel, *, quality: str, max_attempts: int) -> Job:
    """A scheduled (or manual "check now") look for new uploads on a watched channel."""
    return Job(
        kind=JobKind.EXPAND,
        url=channel_service.channel_base_url(channel),
        platform=channel.platform,
        quality=channel.watch_quality or quality,
        title=channel.name,
        priority=PRIORITY_WATCH_CHECK,
        channel_pk=channel.id,
        options={
            "mode": "recent",
            "tabs": channel_service.enabled_tabs(channel),
            "limit": RECENT_LIMIT,
            "child_priority": PRIORITY_NEW_UPLOAD,
        },
        max_attempts=max_attempts,
    )


class ExpandPipeline:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker,
        ytdlp: YtdlpManager,
        reporter: JobReporter,
        policy: Policy,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.ytdlp = ytdlp
        self.reporter = reporter
        self.policy = policy

    def workdir(self, job_id: int) -> Path:
        return self.settings.data_dir / "tmp" / f"job-{job_id}"

    def cleanup(self, job_id: int) -> None:
        shutil.rmtree(self.workdir(job_id), ignore_errors=True)

    def run(self, job_id: int, cancel: CancelToken) -> dict[str, Any]:
        with self.sessions() as db:
            job = db.get_one(Job, job_id)
        try:
            with self.sessions() as db:
                # Listings use the alternate account at most, never the personal one.
                account = account_service.account_for_job(
                    self.settings, db, job.auth_tier, (job.options or {}).get("account_id")
                )
                cookies_file = (
                    account_service.cookie_path(self.settings, account) if account else None
                )
                label = account.label if account else None
            with (
                self.policy.attempt(job.id, account, AttemptKind.LISTING),
                open_job_log(self.settings, job) as log,
            ):
                log.write(f"access: {f'account {label!r}' if label else 'anonymous'}\n")
                return self._run(job, cancel, log, cookies_file)
        except YtdlpError as exc:
            self._record_check_error(job_id, MESSAGES[exc.kind])
            raise

    def _run(
        self, job: Job, cancel: CancelToken, log: TextIO, cookies_file: Path | None
    ) -> dict[str, Any]:
        options = job.options or {}
        mode = options.get("mode", "all")
        parsed = parse_url(job.url)
        if parsed is None or parsed.kind == UrlKind.VIDEO:
            raise YtdlpError(ErrorKind.UNSUPPORTED, f"not a playlist/channel URL: {job.url}")
        limit = options.get("limit")
        workdir = self.workdir(job.id)

        self.reporter.update(job.id, stage=JobStage.RESOLVING)
        with self.ytdlp.using(cookies_file) as runner:
            self.reporter.update(job.id, ytdlp_version=self.ytdlp.version())
            if parsed.kind == UrlKind.PLAYLIST:
                listing = runner.list_entries(
                    job.url, workdir=workdir, limit=limit, log=log, cancel=cancel
                )
                if listing is None:
                    raise YtdlpError(ErrorKind.UNAVAILABLE, "playlist not found")
                listings = {"playlist": listing}
            else:
                listings = self._list_tabs(runner, job, options, workdir, log, cancel)
        meta = next(iter(listings.values()), None)

        with self.sessions.begin() as db:
            job = db.get_one(Job, job.id)
            channel = None
            if parsed.kind == UrlKind.CHANNEL and meta is not None:
                channel = self._update_channel(db, job, meta, options)
            title = (channel.name if channel else None) or (meta or {}).get("title") or job.title
            result = self._queue(db, job, listings, mode, channel)
            if channel is not None:
                channel.last_checked_at = utcnow()
                channel.last_check_error = None
        log.write(f"result: {result}\n")
        if result["queued"]:
            self.reporter.bus.publish(
                "jobs.added", {"parent_id": job.id, "count": result["queued"]}
            )
        if channel is not None and (mode in ("meta", "all") or channel.avatar_file is None):
            self._save_artwork(channel, meta or {})
        return {"result": result, "title": title, "channel_pk": channel.id if channel else None}

    def _list_tabs(
        self,
        runner: YtdlpRunner,
        job: Job,
        options: dict[str, Any],
        workdir: Path,
        log: TextIO,
        cancel: CancelToken,
    ) -> dict[str, dict[str, Any]]:
        tabs = options.get("tabs") or ["videos"]
        limit = options.get("limit")
        listings: dict[str, dict[str, Any]] = {}
        for tab in tabs:
            if tab not in channel_service.TABS:
                continue
            listing = runner.list_entries(
                f"{job.url}/{tab}", workdir=workdir, limit=limit, log=log, cancel=cancel
            )
            if listing is None:
                log.write(f"channel has no {tab} tab\n")
                continue
            listings[tab] = listing
        if not listings and options.get("mode") != "meta":
            raise YtdlpError(ErrorKind.UNAVAILABLE, f"channel has none of the tabs {tabs}")
        return listings

    def _update_channel(
        self, db: DbSession, job: Job, meta: dict[str, Any], options: dict[str, Any]
    ) -> Channel | None:
        fields = channel_service.channel_fields(meta)
        fields["description"] = meta.get("description")
        channel = channel_service.upsert_channel(db, job.platform, fields)
        if channel is None:
            logger.warning("job %s: listing has no channel_id", job.id)
            return None
        job.channel_pk = channel.id
        if options.get("watch") is not None:
            channel.watch_enabled = bool(options["watch"])
            tabs = options.get("tabs")
            if tabs:
                channel.watch_videos = "videos" in tabs
                channel.watch_streams = "streams" in tabs
                channel.watch_shorts = "shorts" in tabs
            if "watch_quality" in options:
                channel.watch_quality = options["watch_quality"]
        return channel

    def _save_artwork(self, channel: Channel, meta: dict[str, Any]) -> None:
        """Fetch avatar/banner outside any DB transaction, then record the paths."""
        root = self.settings.archive_root
        base = archive.channel_dir(root, channel.platform, channel.channel_id)
        saved: dict[str, str] = {}
        for kind, attr in (("avatar", "avatar_file"), ("banner", "banner_file")):
            url = channel_service.pick_thumbnail(meta, kind)
            path = channel_service.save_image(url, base / kind) if url else None
            if path is not None:
                saved[attr] = archive.relative(root, path)
        if saved:
            with self.sessions.begin() as db:
                row = db.get_one(Channel, channel.id)
                for attr, value in saved.items():
                    setattr(row, attr, value)

    def _queue(
        self,
        db: DbSession,
        job: Job,
        listings: dict[str, dict[str, Any]],
        mode: str,
        channel: Channel | None,
    ) -> dict[str, Any]:
        platform = get_platform(job.platform)
        found: dict[str, tuple[str, str | None]] = {}  # video id -> (url, title)
        shorts: set[str] = set()  # ids first seen as a short (shorts tab or /shorts/ URL)
        live = 0
        per_tab: dict[str, int] = {}
        for tab, listing in listings.items():
            per_tab[tab] = 0
            for entry in listing.get("entries") or []:
                if not isinstance(entry, dict) or not entry.get("id"):
                    continue
                parsed = platform.parse_url(entry.get("url") or platform.video_url(entry["id"]))
                if parsed is None or parsed.kind != UrlKind.VIDEO or parsed.id is None:
                    continue
                if entry.get("live_status") in SKIP_LIVE_STATUS:
                    live += 1
                    continue
                per_tab[tab] += 1
                if parsed.id not in found and (tab == "shorts" or parsed.short):
                    shorts.add(parsed.id)
                found.setdefault(parsed.id, (parsed.url, entry.get("title")))

        known = channel_service.known_video_ids(db, job.platform, found)
        new = [vid for vid in found if vid not in known]
        result: dict[str, Any] = {
            "mode": mode,
            "found": len(found),
            "known": len(known),
            "skipped_live": live,
            "tabs": per_tab,
            "queued": 0,
            "ignored": 0,
        }
        if mode == "meta":
            return result
        if mode == "baseline":
            for vid in new:
                channel_service.ignore(db, job.platform, vid, "baseline")
            result["ignored"] = len(new)
            return result

        options = job.options or {}
        quality = options.get("quality") or job.quality
        priority = int(options.get("child_priority", 0))
        for vid in new:
            url, title = found[vid]
            db.add(
                Job(
                    url=url,
                    platform=job.platform,
                    video_id=vid,
                    quality=quality,
                    title=title,
                    priority=priority,
                    content_kind=ContentKind.SHORT if vid in shorts else None,
                    parent_pk=job.id,
                    channel_pk=channel.id if channel else None,
                    max_attempts=self.settings.download_max_attempts,
                )
            )
        result["queued"] = len(new)
        return result

    def _record_check_error(self, job_id: int, message: str) -> None:
        with self.sessions.begin() as db:
            job = db.get_one(Job, job_id)
            channel = db.get(Channel, job.channel_pk) if job.channel_pk else None
            if channel is not None:
                channel.last_checked_at = utcnow()
                channel.last_check_error = message
