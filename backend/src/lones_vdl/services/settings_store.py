"""Typed access to the app_settings key/value table."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as DbSession

from lones_vdl.db.models import AppSetting

PASSWORD_HASH = "auth.password_hash"
YTDLP_LAST_CHECK = "ytdlp.last_checked_at"


def get(db: DbSession, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else None


def put(db: DbSession, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def get_datetime(db: DbSession, key: str) -> datetime | None:
    value = get(db, key)
    return datetime.fromisoformat(value) if value else None
