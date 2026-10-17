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
| MVP content | YouTube videos + Twitch VODs/clips |
| Language | Python 3.11+ |
| API | FastAPI |
| DB | SQLite on **local** disk (not on NAS/SMB/NFS) |
| Media root | Mounted share in production; local folder while developing on Windows |
| Download | yt-dlp (pinned); FFmpeg for probe/remux |
| Playback | Preserve originals; remux-only derivatives when needed |
| Web UI | Svelte + Vite + TypeScript |
| Auth (API) | Shared bearer token; LAN bind |
| YouTube auth | Optional operator-supplied cookies file for yt-dlp |
| Desktop | **Out of scope** — LAN/VPN web UI is sufficient; no separate desktop client |
| Cross-site identity | Manual **creator hub** linking channels across platforms |

## Components

1. **Platform adapter** — yt-dlp wrapper; YouTube and Twitch URL routing.
2. **Download manager** — queue, concurrency, progress, retry, duplicates.
3. **Storage** — ID-based layout on archive root (`youtube/` / `twitch/`); atomic promote; sidecars.
4. **Integrity** — checksums; rescan/import; DB rebuildable from sidecars.
5. **Metadata index** — SQLite for search/jobs; `content_kind` (`video` / `vod` / `clip`); sidecar JSON is portable truth.
6. **Creator hub** — manual links between `(platform, channel_id)` for related/up-next across sites.
7. **Media processing** — ffprobe; remux for browser play when possible.
8. **HTTP API** — FastAPI surface for the web UI (and optional CLI).
9. **Web UI** — browse, play, enqueue, jobs, creators (sole operator GUI).

## Data flow (single video / VOD / clip)

1. Client enqueues URL (+ quality preference).
2. URL router classifies platform + kind; service resolves stable ID via yt-dlp; reject if already archived.
3. Download into partial directory under `<platform>/<id>/`.
4. On success: promote files, write sidecar + checksums + `content_kind`, update DB.
5. On failure: classify (unavailable vs transient), retry or fail clearly.

Channel expand/watch lists YouTube uploads or Twitch VOD archives (not Twitch clips).

## Storage layout

```text
<ARCHIVE_ROOT>/
  youtube|twitch/
    <video_id>/
      media.<ext>
      metadata.json          # source + archive provenance (incl. content_kind)
      thumbnails/
      subtitles/
      checksums.json
      derivatives/           # remux only; optional
    _channels/<channel_id>/avatar.*
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

0. Foundation (this scaffold) — done
1. Core archive path (API/CLI + yt-dlp + sidecars + DB) — done
2. Web library + remux playback + token auth — done
3. Web job control — done
4. Integrity rescan/verify — done
5. ~~Thin desktop client~~ — cancelled (web over LAN/VPN instead)
6. Twitch VODs/clips + creator hub — done

## Non-goals (near term)

- Separate desktop application (Tauri/Electron)
- Microservices, Redis/Celery unless proven necessary
- Active livestream recording
- Twitch clip auto-watch / channel clip expand
- Transcoding pipeline (re-encode)
- Multi-user tenancy / public SaaS
- Public internet exposure (LAN + VPN only)
