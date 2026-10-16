"""Netscape cookies.txt filtering for archive platforms (YouTube now, Twitch later)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

# Domains whose cookies may be needed for authenticated downloads.
# Match is suffix-based on the cookie domain field (leading dots ignored).
PLATFORM_COOKIE_DOMAINS: dict[str, tuple[str, ...]] = {
    "youtube": (
        "youtube.com",
        "youtu.be",
        "googlevideo.com",
        "ytimg.com",
        "ggpht.com",
        "google.com",  # login / consent often required for YouTube
        "googleapis.com",
        "gstatic.com",
        "googleusercontent.com",
    ),
    "twitch": (
        "twitch.tv",
        "ttvnw.net",
        "twitchcdn.net",
        "jtvnw.net",
        "twitchusercontent.com",
    ),
}


@dataclass(frozen=True)
class CookieFilterResult:
    platforms: list[str]
    domains_allowed: list[str]
    lines_before: int
    lines_after: int
    cookies_before: int
    cookies_after: int
    cookies_removed: int
    backup_path: str | None


def normalize_domain(domain: str) -> str:
    return domain.strip().lstrip(".").lower()


def domain_allowed(cookie_domain: str, allowed_suffixes: set[str]) -> bool:
    host = normalize_domain(cookie_domain)
    if not host:
        return False
    for suffix in allowed_suffixes:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def allowed_domains_for_platforms(platforms: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for platform in platforms:
        key = platform.strip().lower()
        for domain in PLATFORM_COOKIE_DOMAINS.get(key, ()):
            if domain not in seen:
                seen.add(domain)
                ordered.append(domain)
    return ordered


def _is_cookie_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    # Netscape rows are tab-separated with at least 7 fields.
    return "\t" in line and len(line.split("\t")) >= 6


def filter_netscape_cookies(
    source: Path,
    *,
    platforms: list[str],
    destination: Path | None = None,
    write_backup: bool = True,
) -> CookieFilterResult:
    """Keep only cookie rows for the given platforms; rewrite file atomically."""
    if not source.is_file():
        raise FileNotFoundError(f"Cookies file not found: {source}")

    platforms_norm = [p.strip().lower() for p in platforms if p.strip()]
    unknown = [p for p in platforms_norm if p not in PLATFORM_COOKIE_DOMAINS]
    if unknown:
        raise ValueError(f"Unknown cookie platforms: {', '.join(unknown)}")
    if not platforms_norm:
        raise ValueError("At least one cookie platform is required")

    allowed = set(allowed_domains_for_platforms(platforms_norm))
    text = source.read_text(encoding="utf-8", errors="replace")
    raw_lines = text.splitlines()

    kept: list[str] = []
    cookies_before = 0
    cookies_after = 0
    for line in raw_lines:
        if not _is_cookie_line(line):
            kept.append(line)
            continue
        cookies_before += 1
        domain = line.split("\t", 1)[0]
        if domain_allowed(domain, allowed):
            kept.append(line)
            cookies_after += 1

    dest = destination or source
    backup_path: str | None = None
    if write_backup and dest.exists() and dest.resolve() == source.resolve():
        backup = source.with_suffix(source.suffix + ".bak")
        shutil.copy2(source, backup)
        backup_path = str(backup)

    payload = "\n".join(kept)
    if payload and not payload.endswith("\n"):
        payload += "\n"
    # Ensure a header comment if the file somehow lost it.
    if not any(line.startswith("#") for line in kept):
        payload = (
            "# Netscape HTTP Cookie File\n"
            "# Filtered by Lones-VDL for archive platforms: "
            + ", ".join(platforms_norm)
            + "\n"
            + payload
        )

    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(dest)

    return CookieFilterResult(
        platforms=platforms_norm,
        domains_allowed=sorted(allowed),
        lines_before=len(raw_lines),
        lines_after=len(kept),
        cookies_before=cookies_before,
        cookies_after=cookies_after,
        cookies_removed=cookies_before - cookies_after,
        backup_path=backup_path,
    )


def count_cookie_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if _is_cookie_line(line)
    )
