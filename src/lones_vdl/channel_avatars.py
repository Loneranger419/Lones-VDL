"""Fetch and store per-channel avatar images under platform/_channels/."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lones_vdl.errors import LonesVdlError
from lones_vdl.platform.ytdlp import YtdlpAdapter
from lones_vdl.storage import PLATFORM_TWITCH, channel_paths, find_channel_avatar

logger = logging.getLogger(__name__)

# Public Twitch web Client-ID (same class of id yt-dlp uses for GQL).
_TWITCH_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
_TWITCH_LOGIN_RE = re.compile(
    r"(?:www\.)?twitch\.tv/([A-Za-z0-9_]{3,25})(?:/|$|\?)",
    re.IGNORECASE,
)


def channel_url_from_source(source: dict[str, Any]) -> str | None:
    for key in ("channel_url", "uploader_url"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    webpage = source.get("webpage_url") or source.get("original_url")
    if isinstance(webpage, str):
        login = twitch_login_from_url(webpage)
        if login:
            return f"https://www.twitch.tv/{login}"
    # Twitch VODs often only expose uploader_id as the channel login.
    uploader_id = source.get("uploader_id")
    if isinstance(uploader_id, str) and re.fullmatch(r"[A-Za-z0-9_]{3,25}", uploader_id):
        if not uploader_id.isdigit():
            return f"https://www.twitch.tv/{uploader_id}"
    return None


def twitch_login_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _TWITCH_LOGIN_RE.search(url)
    if not match:
        return None
    login = match.group(1)
    if login.lower() in {"videos", "directory", "clips", "downloads", "settings"}:
        return None
    return login.lower()


def pick_avatar_url(raw: dict[str, Any]) -> str | None:
    """Prefer yt-dlp channel/playlist avatar thumbnail entries."""
    thumbs = raw.get("thumbnails")
    if isinstance(thumbs, list):
        preferred: str | None = None
        fallback: str | None = None
        for entry in thumbs:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            thumb_id = str(entry.get("id") or "")
            if "avatar" in thumb_id.lower() or "profile" in thumb_id.lower():
                preferred = url.strip()
            fallback = url.strip()
        if preferred:
            return preferred
        if fallback:
            return fallback
    for key in (
        "thumbnail",
        "channel_thumbnail",
        "uploader_avatar_url",
        "profileImageURL",
        "profile_image_url",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def fetch_twitch_profile_image_url(
    *,
    login: str | None = None,
    user_id: str | None = None,
) -> str | None:
    """Resolve a Twitch channel profile image via GQL, then og:image fallback."""
    login_norm = (login or "").strip().lstrip("@").lower() or None
    id_norm = (user_id or "").strip() or None
    gql_url = _twitch_gql_profile_image(login=login_norm, user_id=id_norm)
    if gql_url:
        return gql_url
    if login_norm:
        return _twitch_og_image(login_norm)
    return None


def _twitch_gql_profile_image(
    *,
    login: str | None = None,
    user_id: str | None = None,
) -> str | None:
    if login:
        payload = {
            "query": (
                "query($login: String!){ user(login: $login){ profileImageURL(width: 300) } }"
            ),
            "variables": {"login": login},
        }
    elif user_id:
        payload = {
            "query": ("query($id: ID!){ user(id: $id){ profileImageURL(width: 300) } }"),
            "variables": {"id": user_id},
        }
    else:
        return None
    request = urllib.request.Request(
        "https://gql.twitch.tv/gql",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Client-ID": _TWITCH_GQL_CLIENT_ID,
            "Content-Type": "application/json",
            "User-Agent": "Lones-VDL/0.1 (channel avatar)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.info("Twitch GQL avatar lookup failed for %s/%s: %s", login, user_id, exc)
        return None
    user = (data.get("data") or {}).get("user") or {}
    url = user.get("profileImageURL")
    if isinstance(url, str) and url.startswith("http"):
        return url
    return None


def _twitch_og_image(login: str) -> str | None:
    request = urllib.request.Request(
        f"https://www.twitch.tv/{login}",
        headers={"User-Agent": "Lones-VDL/0.1 (channel avatar)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("Twitch page avatar scrape failed for %s: %s", login, exc)
        return None
    match = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    if not match:
        match = re.search(
            r"https://static-cdn\.jtvnw\.net/jtv_user_pictures/[^\"'\s]+profile_image[^\"'\s]*",
            html,
        )
        return match.group(0) if match else None
    return match.group(1)


def _download_image(url: str, dest: Path) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Lones-VDL/0.1 (channel avatar)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("Avatar HTTP fetch failed: %s", exc)
        return None
    if not data:
        return None
    dest.write_bytes(data)
    return dest


def _avatar_dest(dest_dir: Path, image_url: str) -> Path:
    path = urlparse(image_url).path
    suffix = Path(path).suffix.lower()
    ext = suffix.lstrip(".") if suffix in {".jpg", ".jpeg", ".png", ".webp"} else "jpg"
    return dest_dir / f"avatar.{ext}"


def ensure_channel_avatar(
    *,
    archive_root: Path,
    platform: str,
    channel_id: str,
    channel_url: str | None,
    adapter: YtdlpAdapter,
) -> Path | None:
    """Return existing avatar or fetch once. Best-effort (never raises)."""
    paths = channel_paths(archive_root, platform, channel_id)
    existing = find_channel_avatar(paths)
    if existing is not None:
        return existing

    if platform == PLATFORM_TWITCH:
        login = twitch_login_from_url(channel_url)
        if not login and channel_id and not channel_id.isdigit():
            login = channel_id.strip().lstrip("@").lower()
        user_id = channel_id if channel_id and channel_id.isdigit() else None
        image_url = fetch_twitch_profile_image_url(login=login, user_id=user_id)
        if image_url:
            dest = _avatar_dest(paths.dir, image_url)
            saved = _download_image(image_url, dest)
            if saved is not None:
                return saved

    if not channel_url:
        return None
    try:
        return adapter.download_channel_avatar(channel_url, dest_dir=paths.dir)
    except LonesVdlError as exc:
        logger.info("Channel avatar failed for %s: %s", channel_id, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — polish must not break archives
        logger.info("Channel avatar error for %s: %s", channel_id, exc)
        return None


def channel_has_avatar(archive_root: Path, platform: str, channel_id: str) -> bool:
    return find_channel_avatar(channel_paths(archive_root, platform, channel_id)) is not None


def resolve_channel_avatar_file(
    archive_root: Path,
    platform: str,
    channel_id: str,
) -> Path | None:
    return find_channel_avatar(channel_paths(archive_root, platform, channel_id))
