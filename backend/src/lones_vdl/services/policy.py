"""YouTube download policy: pacing, daily caps, rate-limit pause, and attempt records.

Goal: less account exposure and fewer rate-limit problems. None of this guarantees protection
from account restrictions. The worker asks `Snapshot.ready_at(job)` when a job may start; the
pipelines wrap each request cycle in `Policy.attempt(...)` so `access_attempts` holds the facts
the caps are computed from. This is the app's own accounting, separate from yt-dlp's retries.

Rules (see docs/download-policy-design.md):
- one video at a time (the download lane has concurrency 1);
- a random 15-30 s (configurable) pause after each video attempt;
- caps over a rolling 24 h: all videos, and those that used an account. Only attempts that
  start downloading count, including ones that fail afterwards;
- at least AUTH_GAP_SECONDS between attempts that use an account;
- a rate limit pauses all YouTube work with growing backoff; accounts are never rotated.
"""

from __future__ import annotations

import contextlib
import json
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import (
    AccessAttempt,
    Account,
    AttemptKind,
    AuthTier,
    Job,
    JobKind,
)
from lones_vdl.services import cookies as cookie_service
from lones_vdl.services import settings_store
from lones_vdl.ytdlp import Cancelled, ErrorKind, YtdlpError

if TYPE_CHECKING:
    from lones_vdl.services.runtime import RuntimeConfig

# Module-level so tests can shrink them.
DELAY_FLOOR = 15.0
DELAY_CEIL = 30.0
AUTH_GAP_SECONDS = 15.0
WINDOW = timedelta(hours=24)
# Pause after the 1st, 2nd, ... consecutive rate limit; the last value repeats.
BACKOFF_SECONDS: tuple[float, ...] = (15 * 60, 30 * 60, 60 * 60, 2 * 60 * 60, 6 * 60 * 60)

PAUSE_KEY = "policy.pause"
NEXT_VIDEO_KEY = "policy.next_video_at"
# Jobs that talk to YouTube; maintenance jobs (verify, rescan) are never gated.
YOUTUBE_KINDS = (JobKind.DOWNLOAD, JobKind.EXPAND, JobKind.SUBTITLES)


@dataclass(frozen=True)
class Pause:
    until: datetime | None
    reason: str | None
    strikes: int

    @property
    def active(self) -> bool:
        return self.until is not None and self.until > utcnow()


def get_pause(db: DbSession) -> Pause:
    raw = settings_store.get(db, PAUSE_KEY)
    if not raw:
        return Pause(None, None, 0)
    data = json.loads(raw)
    until = datetime.fromisoformat(data["until"]) if data.get("until") else None
    return Pause(until, data.get("reason"), int(data.get("strikes", 0)))


def _put_pause(db: DbSession, pause: Pause) -> None:
    payload = {
        "until": pause.until.isoformat() if pause.until else None,
        "reason": pause.reason,
        "strikes": pause.strikes,
    }
    settings_store.put(db, PAUSE_KEY, json.dumps(payload))


def register_rate_limit(db: DbSession, reason: str) -> datetime:
    """Pause all YouTube work with growing backoff. Returns when it ends."""
    strikes = get_pause(db).strikes + 1
    delay = BACKOFF_SECONDS[min(strikes - 1, len(BACKOFF_SECONDS) - 1)]
    until = utcnow() + timedelta(seconds=delay)
    _put_pause(db, Pause(until, reason, strikes))
    return until


def clear_pause(db: DbSession) -> None:
    _put_pause(db, Pause(None, None, 0))


def _next_video_at(db: DbSession) -> datetime | None:
    raw = settings_store.get(db, NEXT_VIDEO_KEY)
    return datetime.fromisoformat(raw) if raw else None


def _cap_ready(starts: list[datetime], cap: int, now: datetime) -> datetime:
    """When another download may start, given sorted start times inside the window."""
    if len(starts) < cap:
        return now
    return starts[len(starts) - cap] + WINDOW


@dataclass(frozen=True)
class Snapshot:
    """The policy state at one moment; answers when each job may start."""

    now: datetime
    pause_until: datetime | None
    next_video_at: datetime | None
    last_auth_at: datetime | None
    total_ready: datetime
    auth_ready: datetime

    def ready_at(self, job: Job) -> datetime:
        if job.kind not in YOUTUBE_KINDS:
            return self.now
        ready = self.now
        if self.pause_until:
            ready = max(ready, self.pause_until)
        uses_account = job.auth_tier >= AuthTier.ALTERNATE
        if uses_account and self.last_auth_at:
            ready = max(ready, self.last_auth_at + timedelta(seconds=AUTH_GAP_SECONDS))
        if job.kind == JobKind.DOWNLOAD:
            if self.next_video_at:
                ready = max(ready, self.next_video_at)
            ready = max(ready, self.total_ready)
            if uses_account:
                ready = max(ready, self.auth_ready)
        return ready


class Policy:
    def __init__(self, settings: Settings, runtime: RuntimeConfig, sessions: sessionmaker) -> None:
        self.settings = settings
        self.runtime = runtime
        self.sessions = sessions

    # --- gate ------------------------------------------------------------------------

    def snapshot(self, db: DbSession, now: datetime | None = None) -> Snapshot:
        now = now or utcnow()
        cfg = self.runtime.current
        pause = get_pause(db)
        starts = list(
            db.execute(
                select(AccessAttempt.download_started_at, AccessAttempt.account_pk)
                .where(
                    AccessAttempt.kind == AttemptKind.VIDEO,
                    AccessAttempt.download_started_at >= now - WINDOW,
                )
                .order_by(AccessAttempt.download_started_at)
            )
        )
        all_starts = [row[0] for row in starts]
        auth_starts = [row[0] for row in starts if row[1] is not None]
        last_auth = db.scalars(
            select(AccessAttempt)
            .where(AccessAttempt.account_pk.is_not(None))
            .order_by(AccessAttempt.id.desc())
            .limit(1)
        ).first()
        return Snapshot(
            now=now,
            pause_until=pause.until if pause.until and pause.until > now else None,
            next_video_at=_next_video_at(db),
            last_auth_at=(last_auth.finished_at or last_auth.started_at) if last_auth else None,
            total_ready=_cap_ready(all_starts, cfg.daily_download_cap, now),
            auth_ready=_cap_ready(auth_starts, cfg.daily_auth_cap, now)
            if cfg.daily_auth_cap
            else now + WINDOW,
        )

    def status(self, db: DbSession) -> dict[str, object]:
        """Counts for the UI: today's use against the caps, plus the pause."""
        now = utcnow()
        snap = self.snapshot(db, now)
        cfg = self.runtime.current
        rows = list(
            db.execute(
                select(AccessAttempt.account_pk).where(
                    AccessAttempt.kind == AttemptKind.VIDEO,
                    AccessAttempt.download_started_at >= now - WINDOW,
                )
            )
        )
        week = db.scalars(
            select(AccessAttempt.outcome).where(
                AccessAttempt.kind == AttemptKind.VIDEO,
                AccessAttempt.account_pk.is_(None),
                AccessAttempt.started_at >= now - timedelta(days=7),
                AccessAttempt.outcome.is_not(None),
                AccessAttempt.outcome.not_in(("cancelled", "interrupted")),
            )
        ).all()
        return {
            "anonymous_ok_7d": sum(1 for o in week if o == "ok"),
            # Anonymous access was refused (login, age, or bot check): the case worth watching.
            "anonymous_refused_7d": sum(1 for o in week if o == str(ErrorKind.COOKIES_MISSING)),
            "anonymous_other_7d": sum(
                1 for o in week if o not in ("ok", str(ErrorKind.COOKIES_MISSING))
            ),
            "downloads_24h": len(rows),
            "authenticated_24h": sum(1 for (account,) in rows if account is not None),
            "daily_download_cap": cfg.daily_download_cap,
            "daily_auth_cap": cfg.daily_auth_cap,
            "paused_until": snap.pause_until,
            "pause_reason": get_pause(db).reason if snap.pause_until else None,
            "next_video_at": (
                snap.next_video_at if snap.next_video_at and snap.next_video_at > now else None
            ),
        }

    # --- attempts --------------------------------------------------------------------

    @contextlib.contextmanager
    def attempt(
        self, job_id: int | None, account: Account | None, kind: str
    ) -> Iterator[AttemptHandle]:
        """Record one request cycle and its outcome; reflect results in account health."""
        with self.sessions.begin() as db:
            row = AccessAttempt(
                job_pk=job_id, account_pk=account.id if account else None, kind=kind
            )
            db.add(row)
            db.flush()
            attempt_id = row.id
        handle = AttemptHandle(self, attempt_id)
        account_id = account.id if account else None
        try:
            yield handle
        except BaseException as exc:
            if isinstance(exc, Cancelled):
                outcome = "cancelled"
            elif isinstance(exc, YtdlpError):
                outcome = str(exc.kind)
            else:
                outcome = "error"
            self._finish(attempt_id, kind, outcome)
            if isinstance(exc, YtdlpError) and exc.kind == ErrorKind.COOKIES_INVALID and account_id:
                self._account_health(account_id, cookie_service.INVALID, exc.message)
            raise
        else:
            self._finish(attempt_id, kind, "ok")
            if account_id:
                self._account_health(account_id, cookie_service.OK, None)

    def _finish(self, attempt_id: int, kind: str, outcome: str) -> None:
        now = utcnow()
        with self.sessions.begin() as db:
            row = db.get_one(AccessAttempt, attempt_id)
            row.finished_at = now
            row.outcome = outcome
            if kind == AttemptKind.VIDEO and outcome != "cancelled":
                cfg = self.runtime.current
                delay = random.uniform(cfg.video_delay_min_seconds, cfg.video_delay_max_seconds)
                settings_store.put(db, NEXT_VIDEO_KEY, (now + timedelta(seconds=delay)).isoformat())
            if outcome == "ok" and get_pause(db).strikes:
                _put_pause(db, Pause(None, None, 0))

    def _account_health(self, account_id: int, status: str, detail: str | None) -> None:
        with self.sessions.begin() as db:
            account = db.get(Account, account_id)
            if account is not None:
                account.health_status = status
                account.health_checked_at = utcnow()
                account.health_detail = detail


class AttemptHandle:
    def __init__(self, policy: Policy, attempt_id: int) -> None:
        self._policy = policy
        self.id = attempt_id

    def download_started(self) -> None:
        """The media download begins: from here this attempt counts toward the daily caps."""
        with self._policy.sessions.begin() as db:
            db.get_one(AccessAttempt, self.id).download_started_at = utcnow()


def mark_interrupted(db: DbSession) -> int:
    """Attempts still open after a crash/restart: close them (they keep counting)."""
    rows = db.scalars(select(AccessAttempt).where(AccessAttempt.outcome.is_(None))).all()
    now = utcnow()
    for row in rows:
        row.outcome = "interrupted"
        row.finished_at = now
    return len(rows)
