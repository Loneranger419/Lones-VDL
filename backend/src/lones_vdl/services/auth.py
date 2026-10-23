"""Single-admin password auth with server-side sessions.

The browser holds a random token in an HttpOnly cookie; the DB stores only its sha256, so a
leaked database cannot be replayed as a session.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from lones_vdl.db import utcnow
from lones_vdl.db.models import Session
from lones_vdl.services import settings_store

SESSION_COOKIE = "lvdl_session"
MIN_PASSWORD_LENGTH = 8
# Unremembered sessions end after this much inactivity (the cookie itself is a browser-
# session cookie).
SHORT_SESSION = timedelta(hours=24)
# Avoid a DB write on every request; refresh sliding expiry at most this often.
TOUCH_INTERVAL = timedelta(minutes=10)

_hasher = PasswordHasher()


class PasswordPolicyError(ValueError):
    pass


def password_is_set(db: DbSession) -> bool:
    return settings_store.get(db, settings_store.PASSWORD_HASH) is not None


def set_password(db: DbSession, password: str) -> None:
    """Set/replace the admin password and sign out every existing session."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    settings_store.put(db, settings_store.PASSWORD_HASH, _hasher.hash(password))
    db.execute(delete(Session))


def verify_password(db: DbSession, password: str) -> bool:
    stored = settings_store.get(db, settings_store.PASSWORD_HASH)
    if stored is None:
        return False
    try:
        _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False
    if _hasher.check_needs_rehash(stored):
        settings_store.put(db, settings_store.PASSWORD_HASH, _hasher.hash(password))
    return True


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    db: DbSession,
    *,
    remember: bool,
    session_days: int,
    user_agent: str | None,
    ip: str | None,
) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        Session(
            token_hash=_hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + (timedelta(days=session_days) if remember else SHORT_SESSION),
            remember=remember,
            user_agent=(user_agent or "")[:300] or None,
            ip=ip,
        )
    )
    return token


def get_session(db: DbSession, token: str | None, *, session_days: int) -> Session | None:
    """Return the live session for a token, extending its sliding expiry."""
    if not token:
        return None
    session = db.query(Session).filter_by(token_hash=_hash_token(token)).one_or_none()
    if session is None:
        return None
    now = utcnow()
    if session.expires_at <= now:
        db.delete(session)
        return None
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        session.last_seen_at = now
        session.expires_at = now + (
            timedelta(days=session_days) if session.remember else SHORT_SESSION
        )
    return session


def delete_session(db: DbSession, token: str | None) -> None:
    if token:
        db.execute(delete(Session).where(Session.token_hash == _hash_token(token)))


def purge_expired(db: DbSession) -> int:
    result = db.execute(delete(Session).where(Session.expires_at <= utcnow()))
    return result.rowcount or 0


@dataclass
class _Failures:
    count: int = 0
    locked_until: float = 0.0
    last: float = field(default_factory=time.monotonic)


class LoginThrottle:
    """Per-client backoff: free attempts, then exponentially growing lockouts."""

    def __init__(
        self,
        *,
        free_attempts: int = 5,
        base_lock: float = 30.0,
        max_lock: float = 15 * 60.0,
        forget_after: float = 60 * 60.0,
    ) -> None:
        self.free_attempts = free_attempts
        self.base_lock = base_lock
        self.max_lock = max_lock
        self.forget_after = forget_after
        self._state: dict[str, _Failures] = {}
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> float | None:
        """Seconds until this client may try again, or None if allowed now."""
        now = time.monotonic()
        with self._lock:
            state = self._state.get(client)
            if state is None:
                return None
            if now - state.last > self.forget_after:
                del self._state[client]
                return None
            remaining = state.locked_until - now
            return remaining if remaining > 0 else None

    def failure(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            state = self._state.setdefault(client, _Failures())
            state.count += 1
            state.last = now
            over = state.count - self.free_attempts
            if over >= 0:  # the Nth failure starts the first lockout
                state.locked_until = now + min(self.base_lock * 2**over, self.max_lock)

    def success(self, client: str) -> None:
        with self._lock:
            self._state.pop(client, None)
