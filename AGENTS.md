# AGENTS.md — Lones-VDL

Project-specific instructions for humans and coding agents.
Follow global user rules; do not duplicate them here.

## Purpose

Server-first archival service for YouTube (MVP) and Twitch (later): download, preserve
media + metadata, index in SQLite, browse/play via web UI. Desktop is a thin remote client later.

## Architecture boundaries

Keep these layers separate (see `docs/architecture.md`):

| Area | Responsibility |
|------|----------------|
| `platform` / adapters | yt-dlp invocation and error mapping only |
| download manager | queue, concurrency, progress, retry, duplicates |
| storage | paths, atomic complete, sidecars on archive root |
| integrity | checksums, rescan, verify |
| metadata / DB | SQLite index; sidecars remain portable source of truth |
| media | FFmpeg probe/remux; never overwrite archival originals |
| API | FastAPI HTTP surface |
| web | Svelte UI consuming the API |
| desktop | thin client only (not yet) |

Do not add microservices, Redis, or Celery without an explicit decision.

## External tools

- **yt-dlp** and **FFmpeg** are external dependencies (pinned in deploy docs/image).
- No custom downloaders; no DRM bypass; no automated credential harvesting.
- Cookies: optional operator-supplied Netscape cookie file via config; never commit or log secrets.

## Data and paths

- Archive root and DB path come from config (`LONES_VDL_*`); use `pathlib`; no hard-coded drive letters.
- SQLite must stay on **local** disk; media/sidecars may live on a mounted share.
- Prefer ID-based directories under `youtube/<video_id>/`.

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

Twitch, playlists/channels, live recording, transcoding, multi-user auth, desktop app.
