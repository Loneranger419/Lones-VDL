"""Cookie files: describe one without exposing values, and test it against a restricted video.

Never returns or logs cookie values; status reports names and expiry dates only. Which file
belongs to which account is services/accounts.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DbSession

from lones_vdl import cookie_jar
from lones_vdl.config import Settings
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


def get_health(db: DbSession) -> CookieHealth | None:
    raw = settings_store.get(db, HEALTH_KEY)
    return CookieHealth.model_validate_json(raw) if raw else None


def describe(path: Path, health: CookieHealth | None) -> CookieStatus:
    """Report a cookie file's state: names and expiry dates only, never values."""
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


def test(settings: Settings, ytdlp: YtdlpManager, cookies_file: Path) -> tuple[str, str | None]:
    """Resolve the configured age-restricted video. Returns (health status, detail)."""
    if not cookies_file.is_file():
        return MISSING, None
    parsed = parse_url(settings.cookie_test_url)
    if parsed is None or parsed.kind != UrlKind.VIDEO:
        return ERROR, "LONES_VDL_COOKIE_TEST_URL is not a YouTube video URL"
    workdir = settings.data_dir / "tmp" / f"cookie-test-{uuid.uuid4().hex}"
    try:
        with ytdlp.using(cookies_file) as runner:
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
