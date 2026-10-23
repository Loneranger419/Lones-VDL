"""Import a browser cookie export: keep only what yt-dlp needs, store it privately."""

from __future__ import annotations

from lones_vdl import cookie_jar
from lones_vdl.config import Settings

PLATFORMS = ["youtube"]


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
