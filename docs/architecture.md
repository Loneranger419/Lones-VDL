# Lones-VDL Architecture

Approved foundation for the YouTube & Twitch video archival system.
Implementation follows milestones; this document is the source of truth for boundaries.

## Goals

- Reliable long-term archival of video and metadata (YouTube first; Twitch later).
- Correctness and integrity over development speed.
- Server-first deployment; develop/test on Windows, promote to headless Linux/Docker.
- LAN-only access initially; later access via operator VPN.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Topology | Server-first modular monolith |
| MVP content | YouTube individual videos |
| Language | Python 3.11+ |
| API | FastAPI |
| DB | SQLite on **local** disk (not on NAS/SMB/NFS) |
| Media root | Mounted share in production; local folder while developing on Windows |
| Download | yt-dlp (pinned); FFmpeg for probe/remux |
| Playback | Preserve originals; remux-only derivatives when needed |
| Web UI | Svelte + Vite + TypeScript |
| Auth (API) | Shared bearer token; LAN bind |
| YouTube auth | Optional operator-supplied cookies file for yt-dlp |
| Desktop | Thin remote client after web job control (Milestone 5) |

## Components

1. **Platform adapter** — yt-dlp wrapper; YouTube first.
2. **Download manager** — queue, concurrency, progress, retry, duplicates.
3. **Storage** — ID-based layout on archive root; atomic promote; sidecars.
4. **Integrity** — checksums; rescan/import; DB rebuildable from sidecars.
5. **Metadata index** — SQLite for search/jobs; sidecar JSON is portable truth.
6. **Media processing** — ffprobe; remux for browser play when possible.
7. **HTTP API** — FastAPI; shared by web and future desktop.
8. **Web UI** — browse, play, enqueue (primary operator UI).
9. **Desktop** — deferred thin client against the same API.

## Data flow (single YouTube video)

1. Client enqueues URL (+ quality preference).
2. Service resolves stable ID via yt-dlp; reject/return if already archived.
3. Download into partial directory under `youtube/<id>/`.
4. On success: promote files, write sidecar + checksums, update DB.
5. On failure: classify (unavailable vs transient), retry or fail clearly.

## Storage layout

```text
<ARCHIVE_ROOT>/
  youtube/
    <video_id>/
      media.<ext>
      metadata.json          # source + archive provenance
      thumbnails/
      subtitles/
      checksums.json
      derivatives/           # remux only; optional
```

## Security

- Do not expose the service to the public internet in MVP.
- Secrets (API token, cookies file) outside Git and outside the archive share.
- Cookies: operator-placed Netscape `cookies.txt`; never logged; no automated login or DRM bypass.

## Development vs deploy

- **Windows:** venv, `uvicorn` / `python -m lones_vdl`, local archive path, `scripts/check.ps1`.
- **Linux later:** Docker Compose with NAS bind-mount for archive root; SQLite on a local volume.
- Do not use full image rebuild as the primary edit loop.

## Milestones

0. Foundation (this scaffold)
1. Core archive path (API/CLI + yt-dlp + sidecars + DB)
2. Web library + remux playback + token auth
3. Web job control
4. Integrity rescan/verify
5. Thin desktop client

## Non-goals (near term)

- Microservices, Redis/Celery unless proven necessary
- Active livestream recording
- Transcoding pipeline (re-encode)
- Multi-user tenancy / public SaaS
