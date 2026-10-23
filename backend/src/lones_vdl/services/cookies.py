"""Cookie jar management: import a browser export, report status, test, remove.

Never returns or logs cookie values; status reports names and expiry dates only.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session as DbSession

from lones_vdl import cookie_jar
from lones_vdl.config import Settings
from lones_vdl.db import utcnow
from lones_vdl.platforms import UrlKind, parse_url
from lones_vdl.schemas import CookieHealth, CookieStatus
from lones_vdl.services import settings_store
from lones_vdl.ytdlp import ErrorKind, YtdlpError, YtdlpManager
from lones_vdl.ytdlp.errors import error_lines

PLATFORMS = ["youtube"]
MAX_IMPORT_BYTES = 1024 * 1024
HEALTH_KEY = "cookies.health"

# Health values. "untested" = imported but no download/test has used them yet.
OK, INVALID, MISSING, UNTESTED, ERROR = "ok", "invalid", "missing", "untested", "error"


class CookieImportError(ValueError):
    pass


def import_cookies(settings: Settings, text: str) -> cookie_jar.FilterSummary:
    cookies, summary = cookie_jar.filter_cookies(text, PLATFORMS)
    if not summary.kept:
        raise CookieImportError("no YouTube cookies found in that file")
    if not any(summary.auth_cookies.get(p) for p in PLATFORMS):
        raise CookieImportError("no YouTube login cookies found; export while signed in")
    cookie_jar.write_private(settings.cookies_file, cookie_jar.serialize(cookies))
    return summary


def get_health(db: DbSession) -> CookieHealth | None:
    raw = settings_store.get(db, HEALTH_KEY)
    return CookieHealth.model_validate_json(raw) if raw else None


def record_health(db: DbSession, status: str, detail: str | None = None) -> CookieHealth:
    health = CookieHealth(status=status, checked_at=utcnow(), detail=detail)
    settings_store.put(db, HEALTH_KEY, health.model_dump_json())
    return health


def status(settings: Settings, db: DbSession) -> CookieStatus:
    path = settings.cookies_file
    health = get_health(db)
    if not path.is_file():
        return CookieStatus(present=False, health=health)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    cookies, summary = cookie_jar.filter_cookies(text, PLATFORMS)
    login: dict[str, str] = {}
    for platform in PLATFORMS:
        login.update(summary.auth_cookies.get(platform, {}))
    dated = sorted(v for v in login.values() if v != "session")
    return CookieStatus(
        present=True,
        updated_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
        cookie_count=len(cookies),
        login_cookies=login,
        login_expires=dated[0] if dated else None,
        health=health,
    )


def delete(settings: Settings, db: DbSession) -> None:
    settings.cookies_file.unlink(missing_ok=True)
    record_health(db, MISSING)


def test(settings: Settings, ytdlp: YtdlpManager) -> tuple[str, str | None]:
    """Resolve the configured age-restricted video. Returns (health status, detail)."""
    if not settings.cookies_file.is_file():
        return MISSING, None
    parsed = parse_url(settings.cookie_test_url)
    if parsed is None or parsed.kind != UrlKind.VIDEO:
        return ERROR, "LONES_VDL_COOKIE_TEST_URL is not a YouTube video URL"
    workdir = settings.data_dir / "tmp" / f"cookie-test-{uuid.uuid4().hex}"
    try:
        with ytdlp.using() as runner:
            info, _ = runner.resolve(parsed.url, quality="best", workdir=workdir, verbose=False)
    except YtdlpError as exc:
        if exc.kind in (ErrorKind.COOKIES_INVALID, ErrorKind.COOKIES_MISSING):
            return INVALID, exc.message
        lines = error_lines(exc.detail, limit=1)
        return ERROR, f"{exc.message}{f' [{lines[0]}]' if lines else ''}"[:500]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return OK, f"resolved '{info.get('title') or info.get('id')}'"


def summary_payload(summary: cookie_jar.FilterSummary) -> dict[str, Any]:
    """Import result for the API: counts and cookie names, never values."""
    return {
        "kept": summary.kept,
        "dropped_domain": summary.dropped_domain,
        "dropped_expired": summary.dropped_expired,
        "login_cookies": {
            k: v for p in PLATFORMS for k, v in summary.auth_cookies.get(p, {}).items()
        },
        "warnings": summary.warnings,
    }
