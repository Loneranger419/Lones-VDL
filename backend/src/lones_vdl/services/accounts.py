"""Accounts: the signed-in identities yt-dlp may use, each with its own private cookie file.

The download policy picks which account a job may use (see services/policy). Cookie values never
leave the files under secrets/accounts/; everything here reports names and expiry dates only.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lones_vdl import cookie_jar
from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.db.models import Account, AccountRole, AuthTier
from lones_vdl.schemas import CookieHealth, CookieStatus
from lones_vdl.services import cookies as cookie_service
from lones_vdl.services import settings_store
from lones_vdl.ytdlp import ErrorKind, YtdlpError

LEGACY_LABEL = "Alternate"

TIER_ROLE = {AuthTier.ALTERNATE: AccountRole.ALTERNATE, AuthTier.PERSONAL: AccountRole.PERSONAL}


class AccountError(ValueError):
    pass


def cookie_path(settings: Settings, account: Account) -> Path:
    return settings.accounts_dir / f"{account.id}.txt"


def list_accounts(db: DbSession) -> list[Account]:
    return list(db.scalars(select(Account).order_by(Account.id)))


def get(db: DbSession, account_id: int) -> Account | None:
    return db.get(Account, account_id)


def create(db: DbSession, label: str, role: str) -> Account:
    label = label.strip()
    if not label:
        raise AccountError("label is required")
    if role not in AccountRole:
        raise AccountError(f"unknown role: {role}")
    if db.scalars(select(Account.id).where(Account.label == label)).first() is not None:
        raise AccountError(f"an account named {label!r} already exists")
    account = Account(label=label, role=role)
    db.add(account)
    db.flush()
    return account


def rename(db: DbSession, account: Account, label: str) -> None:
    label = label.strip()
    if not label:
        raise AccountError("label is required")
    taken = db.scalars(select(Account.id).where(Account.label == label, Account.id != account.id))
    if taken.first() is not None:
        raise AccountError(f"an account named {label!r} already exists")
    account.label = label


def health(account: Account) -> CookieHealth | None:
    if account.health_status is None or account.health_checked_at is None:
        return None
    return CookieHealth(
        status=account.health_status,
        checked_at=account.health_checked_at,
        detail=account.health_detail,
    )


def record_health(account: Account, status: str, detail: str | None = None) -> None:
    account.health_status = status
    account.health_checked_at = utcnow()
    account.health_detail = detail


def status(settings: Settings, account: Account) -> CookieStatus:
    return cookie_service.describe(cookie_path(settings, account), health(account))


def import_cookies(settings: Settings, account: Account, text: str) -> cookie_jar.FilterSummary:
    """Replace this account's cookies with the allowed-domain cookies from a browser export."""
    cookies, summary = cookie_jar.filter_cookies(text, cookie_service.PLATFORMS)
    if not summary.kept:
        raise cookie_service.CookieImportError("no YouTube cookies found in that file")
    if not any(summary.auth_cookies.get(p) for p in cookie_service.PLATFORMS):
        raise cookie_service.CookieImportError(
            "no YouTube login cookies found; export while signed in"
        )
    path = cookie_path(settings, account)
    path.parent.mkdir(parents=True, exist_ok=True)
    cookie_jar.write_private(path, cookie_jar.serialize(cookies))
    record_health(account, cookie_service.UNTESTED)
    return summary


def has_cookies(settings: Settings, account: Account) -> bool:
    return cookie_path(settings, account).is_file()


def delete_cookies(settings: Settings, account: Account) -> None:
    cookie_path(settings, account).unlink(missing_ok=True)
    record_health(account, cookie_service.MISSING)


def remove(settings: Settings, db: DbSession, account: Account) -> None:
    cookie_path(settings, account).unlink(missing_ok=True)
    db.delete(account)


def account_for_tier(settings: Settings, db: DbSession, tier: int) -> Account | None:
    """The account a job at this tier uses: enabled, with cookies, matching the tier's role."""
    role = TIER_ROLE.get(AuthTier(tier))
    if role is None:
        return None
    candidates = db.scalars(
        select(Account).where(Account.role == role, Account.enabled.is_(True)).order_by(Account.id)
    )
    return next((a for a in candidates if has_cookies(settings, a)), None)


def account_for_job(
    settings: Settings, db: DbSession, tier: int, prefer_id: int | None = None
) -> Account | None:
    """The account a job at this tier runs with; None for anonymous.

    `prefer_id` is an account the user picked for this one job (retry with account).
    Raises COOKIES_MISSING when the tier needs an account that is not set up, so the job
    fails loudly instead of silently running without the access it needs."""
    if tier == AuthTier.ANONYMOUS:
        return None
    account = account_for_tier(settings, db, tier)
    if prefer_id is not None:
        chosen = db.get(Account, prefer_id)
        usable = (
            chosen is not None
            and chosen.enabled
            and chosen.role == TIER_ROLE[AuthTier(tier)]
            and has_cookies(settings, chosen)
        )
        account = chosen if usable else None
    if account is None:
        role = TIER_ROLE[AuthTier(tier)]
        raise YtdlpError(ErrorKind.COOKIES_MISSING, f"no enabled {role} account with cookies")
    return account


def adopt_legacy_cookies(settings: Settings, db: DbSession) -> Account | None:
    """One-time upgrade: the single v2 cookie jar becomes the 'Alternate' account."""
    legacy = settings.cookies_file
    if not legacy.is_file() or db.scalars(select(Account.id)).first() is not None:
        return None
    account = create(db, LEGACY_LABEL, AccountRole.ALTERNATE)
    target = cookie_path(settings, account)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(legacy, target)
    old = cookie_service.get_health(db)
    if old is not None:
        account.health_status = old.status
        account.health_checked_at = old.checked_at
        account.health_detail = old.detail
    settings_store.put(db, cookie_service.HEALTH_KEY, "")
    return account
