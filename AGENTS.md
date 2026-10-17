# AGENTS.md — Lones-VDL

Project-specific instructions for humans and coding agents.
Follow global user rules; do not duplicate them here.

## Purpose

Server-first archival service for YouTube and Twitch: download, preserve media + metadata,
index in SQLite, browse/play via web UI. Creator hub links channels across sites.

## Architecture boundaries

Keep these layers separate (see `docs/architecture.md`):

| Area | Responsibility |
|------|----------------|
| `platform` / adapters | yt-dlp invocation, URL routing, error mapping only |
| download manager | queue, concurrency, progress, retry, duplicates |
| storage | paths, atomic complete, sidecars on archive root |
| integrity | checksums, rescan, verify |
| metadata / DB | SQLite index; sidecars remain portable source of truth |
| media | FFmpeg probe/remux; never overwrite archival originals |
| API | FastAPI HTTP surface |
| web | Svelte UI consuming the API (sole GUI; no desktop app) |

Do not add microservices, Redis, or Celery without an explicit decision.

## External tools

- **yt-dlp** and **FFmpeg** are external dependencies (pinned in deploy docs/image).
- No custom downloaders; no DRM bypass; no automated credential harvesting.
- Cookies: optional operator-supplied Netscape cookie file via config; never commit or log secrets.
- Cookie filter (`POST /api/cookies/filter`) keeps domains for `LONES_VDL_COOKIE_PLATFORMS`
  (default `youtube,twitch`). Never return cookie values from the API.

## Data and paths

- Archive root and DB path come from config (`LONES_VDL_*`); use `pathlib`; no hard-coded drive letters.
- SQLite must stay on **local** disk; media/sidecars may live on a mounted share.
- Prefer ID-based directories under `<platform>/<video_id>/` (`youtube/`, `twitch/`).

## Security

- LAN-only MVP; do not design for public internet exposure.
- API token and cookie files stay out of Git (see `.gitignore`, `.env.example`).

## Verification

One entry point:

- Windows: `powershell -File scripts/check.ps1`
- Linux/make: `make check`

Runs ruff + pytest. Do not claim features work without running checks.
Real YouTube downloads are manual/gated (network, ToS, flakes) — mock yt-dlp in automated tests.

## Development workflow

1. Develop and test on Windows against a local archive folder.
2. Promote the same Git revision to headless Linux/Docker later.
3. Ask before installing dependencies, changing Git remotes, or committing.

## Out of scope until milestones say otherwise

Live recording, Twitch clip auto-watch, transcoding, multi-user auth.
Desktop app cancelled — use the web UI over LAN/VPN.

Playlists/channel uploads + optional channel watch (YouTube uploads / Twitch VODs) are in scope.
Creator hub links are manual (no auto-match).
