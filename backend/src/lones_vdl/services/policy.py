"""YouTube download policy: pacing, daily caps, rate-limit pause, and attempt records.

Goal: less account exposure and fewer rate-limit problems. None of this guarantees protection
from account restrictions. The worker asks `Snapshot.ready_at(job)` when a job may start; the
pipelines wrap each request cycle in `Policy.attempt(...)` so `access_attempts` holds the facts
the caps are computed from. This is the app's own accounting, separate from yt-dlp's retries.

Rules (see docs/download-policy-design.md):
- one video at a time (the download lane has concurrency 1);
- a random 15-30 s (configurable) pause after each video attempt;
- caps over a rolling 24 h, for videos/streams and separately for shorts: all of them, and those
  that used an account. Only attempts that start downloading count, including ones that fail
  afterwards. Shorts also wait while a video or stream is able to run;
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

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import (
    AccessAttempt,
    Account,
    AccountRole,
    AttemptKind,
    AuthTier,
    ContentKind,
    Job,
    JobKind,
    JobStatus,
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
# A short that has to give way to videos is looked at again after this long.
YIELD_SECONDS = 5.0
# Pause after the 1st, 2nd, ... consecutive rate limit; the last value repeats.
BACKOFF_SECONDS: tuple[float, ...] = (15 * 60, 30 * 60, 60 * 60, 2 * 60 * 60, 6 * 60 * 60)

PAUSE_KEY = "policy.pause"
NEXT_VIDEO_KEY = "policy.next_video_at"
# Jobs that talk to YouTube; maintenance jobs (verify, rescan) are never gated.
YOUTUBE_KINDS = (JobKind.DOWNLOAD, JobKind.EXPAND, JobKind.SUBTITLES, JobKind.CHAPTERS)


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
    # When another video / short may start, given the daily caps of its own pool.
    total_ready: datetime
    auth_ready: datetime
    short_total_ready: datetime
    short_auth_ready: datetime
    # Videos or streams are queued and able to run: shorts wait for them.
    videos_waiting: bool

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
            short = job.content_kind == ContentKind.SHORT
            if self.next_video_at:
                ready = max(ready, self.next_video_at)
            # A job the user approved by hand is exempt from the daily total (and is not counted in
            # it); it still waits for the account cap, the delay, and any pause.
            if job.approved_at is None:
                ready = max(ready, self.short_total_ready if short else self.total_ready)
            if uses_account:
                ready = max(ready, self.short_auth_ready if short else self.auth_ready)
            if short and self.videos_waiting:
                ready = max(ready, self.now + timedelta(seconds=YIELD_SECONDS))
        return ready


def _is_short(content_kind: str | None) -> bool:
    return content_kind == ContentKind.SHORT


class Deferred(Exception):
    """A job found out (after resolving) that it must wait; it goes back to the queue unharmed."""

    def __init__(self, until: datetime) -> None:
        super().__init__(f"deferred until {until.isoformat()}")
        self.until = until


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
                select(
                    AccessAttempt.download_started_at,
                    AccessAttempt.account_pk,
                    AccessAttempt.content_kind,
                    Account.role,
                )
                .outerjoin(Account, Account.id == AccessAttempt.account_pk)
                .where(
                    AccessAttempt.kind == AttemptKind.VIDEO,
                    AccessAttempt.download_started_at >= now - WINDOW,
                )
                .order_by(AccessAttempt.download_started_at)
            )
        )
        videos = [(at, acc, role) for at, acc, kind, role in starts if not _is_short(kind)]
        shorts = [(at, acc, role) for at, acc, kind, role in starts if _is_short(kind)]

        def ready(rows: list[tuple[datetime, int | None, str | None]], cap: int, auth_cap: int):
            # A download on the personal account (always approved by hand) counts only towards
            # the account cap, not the daily total.
            total = _cap_ready(
                [at for at, _, role in rows if role != AccountRole.PERSONAL], cap, now
            )
            auth = (
                _cap_ready([at for at, acc, _ in rows if acc is not None], auth_cap, now)
                if auth_cap
                else now + WINDOW
            )
            return total, auth

        total_ready, auth_ready = ready(videos, cfg.daily_download_cap, cfg.daily_auth_cap)
        short_total_ready, short_auth_ready = ready(
            shorts, cfg.shorts_daily_cap, cfg.shorts_daily_auth_cap
        )
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
            total_ready=total_ready,
            auth_ready=auth_ready,
            short_total_ready=short_total_ready,
            short_auth_ready=short_auth_ready,
            videos_waiting=self._videos_waiting(db, total_ready, auth_ready, now),
        )

    @staticmethod
    def _videos_waiting(
        db: DbSession, total_ready: datetime, auth_ready: datetime, now: datetime
    ) -> bool:
        """Is a queued video or stream able to run, apart from shorts? One that is held back
        only by its own daily cap does not count: that wait is for tomorrow, not for shorts."""
        if total_ready > now:
            return False
        rows = db.execute(
            select(Job.auth_tier, func.count())
            .where(
                Job.kind == JobKind.DOWNLOAD,
                Job.status == JobStatus.QUEUED,
                or_(Job.content_kind.is_(None), Job.content_kind != ContentKind.SHORT),
            )
            .group_by(Job.auth_tier)
        )
        anonymous = sum(n for tier, n in rows if tier < AuthTier.ALTERNATE)
        with_account = sum(n for tier, n in rows if tier >= AuthTier.ALTERNATE)
        return anonymous > 0 or (with_account > 0 and auth_ready <= now)

    def defer_if_blocked(self, job: Job) -> None:
        """For a job that only now turned out to be a short: wait if shorts may not run yet."""
        with self.sessions() as db:
            ready = self.snapshot(db).ready_at(job)
        if ready > utcnow():
            raise Deferred(ready)

    def status(self, db: DbSession) -> dict[str, object]:
        """Per-site use of the daily limits for the UI, plus the pause. Only YouTube so far."""
        now = utcnow()
        snap = self.snapshot(db, now)
        cfg = self.runtime.current
        rows = list(
            db.execute(
                select(AccessAttempt.account_pk, AccessAttempt.content_kind, Account.role)
                .outerjoin(Account, Account.id == AccessAttempt.account_pk)
                .where(
                    AccessAttempt.kind == AttemptKind.VIDEO,
                    AccessAttempt.download_started_at >= now - WINDOW,
                )
            )
        )

        def group(key: str, label: str, short: bool, cap: int, auth_cap: int) -> dict[str, object]:
            mine = [(acc, role) for acc, kind, role in rows if _is_short(kind) == short]
            return {
                "key": key,
                "label": label,
                # Personal-account downloads count only as "using an account".
                "used": sum(1 for _, role in mine if role != AccountRole.PERSONAL),
                "cap": cap,
                "auth_used": sum(1 for acc, _ in mine if acc is not None),
                "auth_cap": auth_cap,
            }

        week = db.scalars(
            select(AccessAttempt.outcome).where(
                AccessAttempt.kind == AttemptKind.VIDEO,
                AccessAttempt.account_pk.is_(None),
                AccessAttempt.started_at >= now - timedelta(days=7),
                AccessAttempt.outcome.is_not(None),
                AccessAttempt.outcome.not_in(("cancelled", "interrupted", "deferred")),
            )
        ).all()
        youtube = {
            "platform": "youtube",
            "label": "YouTube",
            "groups": [
                group("videos", "Videos", False, cfg.daily_download_cap, cfg.daily_auth_cap),
                group("shorts", "Shorts", True, cfg.shorts_daily_cap, cfg.shorts_daily_auth_cap),
            ],
            "paused_until": snap.pause_until,
            "pause_reason": get_pause(db).reason if snap.pause_until else None,
            "next_video_at": (
                snap.next_video_at if snap.next_video_at and snap.next_video_at > now else None
            ),
            "anonymous_ok_7d": sum(1 for o in week if o == "ok"),
            # Anonymous access was refused (login, age, or bot check): the case worth watching.
            "anonymous_refused_7d": sum(1 for o in week if o == str(ErrorKind.COOKIES_MISSING)),
            "anonymous_other_7d": sum(
                1 for o in week if o not in ("ok", str(ErrorKind.COOKIES_MISSING))
            ),
        }
        return {"platforms": [youtube]}

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
            elif isinstance(exc, Deferred):
                outcome = "deferred"
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
            if kind == AttemptKind.VIDEO and outcome not in ("cancelled", "deferred"):
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

    def download_started(self, content_kind: str | None = None) -> None:
        """The media download begins: from here this attempt counts toward the daily caps
        (the shorts caps when `content_kind` is "short")."""
        with self._policy.sessions.begin() as db:
            row = db.get_one(AccessAttempt, self.id)
            row.download_started_at = utcnow()
            row.content_kind = content_kind


def mark_interrupted(db: DbSession) -> int:
    """Attempts still open after a crash/restart: close them (they keep counting)."""
    rows = db.scalars(select(AccessAttempt).where(AccessAttempt.outcome.is_(None))).all()
    now = utcnow()
    for row in rows:
        row.outcome = "interrupted"
        row.finished_at = now
    return len(rows)
