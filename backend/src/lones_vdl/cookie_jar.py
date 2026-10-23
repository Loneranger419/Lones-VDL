"""Filter a browser cookie export down to the domains Lones-VDL needs.

Stdlib only. The pure functions here back the cookie import service (Phase 2/3); ``main`` is
the ``lones-vdl cookies`` CLI.

Handles real-world exporter quirks:
- ``#HttpOnly_`` prefixed rows (these are cookies, not comments; YouTube login cookies use it)
- CRLF line endings, blank lines, malformed rows
- expiry written as Chrome/WebKit microseconds since 1601 or as Unix milliseconds
- duplicate (domain, path, name) rows

Never prints or logs cookie values.

Usage:
    lones-vdl cookies secrets/cookies.txt -o secrets/cookies.filtered.txt
    lones-vdl cookies secrets/cookies.txt --replace
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

HEADER = "# Netscape HTTP Cookie File\n# Filtered by Lones-VDL. Do not commit.\n"
HTTPONLY_PREFIX = "#HttpOnly_"

# Cookie domains needed for authenticated downloads, matched on a dot boundary
# (``youtube.com`` matches ``.youtube.com`` and ``m.youtube.com``, not ``evilyoutube.com``).
# Deliberately minimal: google.com cookies (Gmail, Drive, ...) are not needed; verified
# 2026-10-22 with an age-restricted download using youtube.com cookies only.
PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "youtube": ("youtube.com",),
    "twitch": ("twitch.tv",),
}

# Cookies that indicate a signed-in session, per platform.
AUTH_COOKIES: dict[str, tuple[str, ...]] = {
    "youtube": ("SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "LOGIN_INFO"),
    "twitch": ("auth-token",),
}

# WebKit epoch (1601-01-01) to Unix epoch (1970-01-01), in seconds.
WEBKIT_EPOCH_OFFSET = 11_644_473_600


@dataclass(frozen=True)
class Cookie:
    domain: str
    include_subdomains: bool
    path: str
    secure: bool
    expires: int  # Unix seconds; 0 = session cookie
    name: str
    value: str
    http_only: bool = False

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.domain.lower(), self.path, self.name)


@dataclass
class FilterSummary:
    platforms: list[str]
    allowed_domains: list[str]
    rows_read: int = 0
    rows_malformed: int = 0
    kept: int = 0
    dropped_domain: int = 0
    dropped_expired: int = 0
    dropped_duplicate: int = 0
    expiry_normalized: int = 0
    kept_domains: dict[str, int] = field(default_factory=dict)
    # platform -> {cookie name: expiry ISO date or "session"}; names only, never values
    auth_cookies: dict[str, dict[str, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def normalize_expiry(raw: int) -> int:
    """Return expiry as Unix seconds, converting WebKit microseconds or Unix milliseconds."""
    if raw <= 0:
        return 0
    if raw > 10**15:  # WebKit µs since 1601 (~1.3e16 today)
        return max(0, raw // 1_000_000 - WEBKIT_EPOCH_OFFSET)
    if raw > 10**11:  # Unix ms (~1.8e12 today)
        return raw // 1000
    return raw


def parse_line(line: str) -> Cookie | None:
    """Parse one Netscape row. Returns None for comments, blanks, and malformed rows."""
    line = line.rstrip("\r\n")
    http_only = False
    if line.startswith(HTTPONLY_PREFIX):
        http_only = True
        line = line[len(HTTPONLY_PREFIX) :]
    if not line.strip() or line.startswith("#"):
        return None
    parts = line.split("\t")
    if len(parts) < 7:
        return None
    domain, flag, path, secure, expires, name = parts[:6]
    value = "\t".join(parts[6:])
    if not domain or not name:
        return None
    try:
        expiry = int(float(expires)) if expires.strip() else 0
    except ValueError:
        return None
    return Cookie(
        domain=domain.strip(),
        include_subdomains=flag.strip().upper() == "TRUE",
        path=path or "/",
        secure=secure.strip().upper() == "TRUE",
        expires=expiry,
        name=name,
        value=value,
        http_only=http_only,
    )


def is_data_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return stripped.startswith(HTTPONLY_PREFIX) or not stripped.startswith("#")


def allowed_domains(platforms: list[str]) -> list[str]:
    unknown = [p for p in platforms if p not in PLATFORM_DOMAINS]
    if unknown:
        raise ValueError(f"unknown platform(s): {', '.join(unknown)}")
    seen: dict[str, None] = {}
    for platform in platforms:
        for domain in PLATFORM_DOMAINS[platform]:
            seen[domain] = None
    return list(seen)


def domain_allowed(cookie_domain: str, allowed: list[str]) -> bool:
    host = cookie_domain.strip().lstrip(".").lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def format_cookie(cookie: Cookie) -> str:
    prefix = HTTPONLY_PREFIX if cookie.http_only else ""
    return "\t".join(
        [
            prefix + cookie.domain,
            "TRUE" if cookie.include_subdomains else "FALSE",
            cookie.path,
            "TRUE" if cookie.secure else "FALSE",
            str(cookie.expires),
            cookie.name,
            cookie.value,
        ]
    )


def _iso_date(ts: int) -> str:
    return "session" if ts == 0 else time.strftime("%Y-%m-%d", time.gmtime(ts))


def filter_cookies(
    text: str,
    platforms: list[str],
    *,
    now: int | None = None,
    drop_expired: bool = True,
) -> tuple[list[Cookie], FilterSummary]:
    """Parse a Netscape export and keep only cookies for ``platforms``."""
    now = int(time.time()) if now is None else now
    domains = allowed_domains(platforms)
    summary = FilterSummary(platforms=list(platforms), allowed_domains=domains)
    kept: dict[tuple[str, str, str], Cookie] = {}

    for line in text.splitlines():
        if not is_data_line(line):
            continue
        summary.rows_read += 1
        cookie = parse_line(line)
        if cookie is None:
            summary.rows_malformed += 1
            continue
        if not domain_allowed(cookie.domain, domains):
            summary.dropped_domain += 1
            continue
        expires = normalize_expiry(cookie.expires)
        if expires != cookie.expires:
            summary.expiry_normalized += 1
            cookie = Cookie(**{**asdict(cookie), "expires": expires})
        if drop_expired and expires and expires < now:
            summary.dropped_expired += 1
            continue
        existing = kept.get(cookie.key)
        if existing is not None:
            summary.dropped_duplicate += 1
            if existing.expires == 0 or (cookie.expires and cookie.expires <= existing.expires):
                continue
        kept[cookie.key] = cookie

    cookies = list(kept.values())
    summary.kept = len(cookies)
    for cookie in cookies:
        host = cookie.domain.lstrip(".").lower()
        summary.kept_domains[host] = summary.kept_domains.get(host, 0) + 1
    for platform in platforms:
        names = AUTH_COOKIES.get(platform, ())
        # Latest-first so the earliest expiry wins when a name repeats across domains.
        found = {
            c.name: _iso_date(c.expires)
            for c in sorted(cookies, key=lambda c: c.expires or 2**62, reverse=True)
            if c.name in names
        }
        summary.auth_cookies[platform] = found
        if not found:
            summary.warnings.append(f"no {platform} login cookies found; export while signed in")
    if summary.rows_read and summary.kept == 0:
        summary.warnings.append("no cookies kept; check the export and platforms")
    return cookies, summary


def serialize(cookies: list[Cookie]) -> str:
    body = "\n".join(format_cookie(c) for c in sorted(cookies, key=lambda c: c.key))
    return HEADER + body + ("\n" if body else "")


def write_private(path: Path, content: str) -> None:
    """Atomically write ``content`` to ``path`` readable only by the owner (where supported)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cookies-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _print_summary(summary: FilterSummary, out: Path | None) -> None:
    print(f"read {summary.rows_read} rows ({summary.rows_malformed} malformed)")
    print(
        f"kept {summary.kept}; dropped {summary.dropped_domain} other-domain, "
        f"{summary.dropped_expired} expired, {summary.dropped_duplicate} duplicate"
    )
    if summary.expiry_normalized:
        print(f"normalized {summary.expiry_normalized} non-Unix expiry timestamps")
    for host, count in sorted(summary.kept_domains.items()):
        print(f"  {host}: {count}")
    for platform, found in summary.auth_cookies.items():
        detail = ", ".join(f"{n} (expires {d})" for n, d in found.items()) or "none"
        print(f"{platform} login cookies: {detail}")
    for warning in summary.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if out is not None:
        print(f"wrote {out}")


def main(argv: list[str] | None = None, *, prog: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0])
    parser.add_argument("input", type=Path, help="Netscape cookies.txt exported from a browser")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("-o", "--output", type=Path, help="write filtered cookies here")
    target.add_argument(
        "--replace", action="store_true", help="overwrite the input with the filtered result"
    )
    parser.add_argument(
        "--platforms",
        default="youtube",
        help=f"comma-separated, from: {', '.join(PLATFORM_DOMAINS)} (default: youtube)",
    )
    parser.add_argument("--keep-expired", action="store_true", help="do not drop expired cookies")
    parser.add_argument("--json", action="store_true", help="print summary as JSON")
    args = parser.parse_args(argv)

    platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    try:
        text = args.input.read_text(encoding="utf-8-sig", errors="replace")
        cookies, summary = filter_cookies(text, platforms, drop_expired=not args.keep_expired)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out = args.input if args.replace else args.output
    if out is not None and summary.kept:
        write_private(out, serialize(cookies))
    elif out is not None:
        out = None  # never overwrite with an empty jar

    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        _print_summary(summary, out)
    return 0 if summary.kept and not summary.warnings else 1
