# Lones-VDL

Cross-platform (Windows develop → Linux/Docker deploy) video archival system focused on
reliable long-term preservation of YouTube and Twitch content and metadata.

**Status:** YouTube + Twitch VODs/clips; View/Download browse; playlists/channel expand + watch; creator hub.

## Architecture

See [docs/architecture.md](docs/architecture.md) and [AGENTS.md](AGENTS.md).

## Requirements (development)

- Python 3.11+
- (Later) yt-dlp, FFmpeg on PATH or via Docker image
- Node.js 20+ when building the web UI (placeholder present; not required for API smoke tests)

## Quick start (Windows)

One-shot local UI + API (verifies `.venv` / deps). Prefers **Windows Terminal** with API | Vite split panes in one window; API pane restarts with Ctrl+C then Enter (no new window). Falls back to separate consoles if `wt.exe` is missing.

```powershell
# First time (creates .venv, pip install -e ".[dev]", npm install, copies .env):
powershell -File scripts\dev.ps1 -Install

# Later:
powershell -File scripts\dev.ps1
# or: scripts\dev.cmd
```

Flags: `-ApiOnly`, `-WebOnly`, `-NoTerminal` (skip Windows Terminal). API: `http://127.0.0.1:8080` · UI: `http://127.0.0.1:5173` (enter `LONES_VDL_API_TOKEN` from `.env`).

Manual equivalent:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
copy .env.example .env
powershell -File scripts\check.ps1
python -m lones_vdl serve
```

Install **yt-dlp** (and FFmpeg) on PATH for real downloads. Automated tests mock yt-dlp.

For fewer YouTube TLS / rate-limit issues, install a yt-dlp build with impersonation
support (e.g. official `yt-dlp.exe`, or `pip install "yt-dlp[default,curl-cffi]"`) and
confirm with `yt-dlp --list-impersonate-targets`.

Downloads are two-phase: media first, then a best-effort English subtitle pass. Subtitle
429s no longer fail the archive. Auto-sub language wildcards (`en.*`) are avoided because
they request many translated tracks and trip rate limits on playlists.

Health check: `GET http://127.0.0.1:8080/api/health`

Enqueue (API):

```powershell
curl -X POST http://127.0.0.1:8080/api/jobs `
  -H "Authorization: Bearer change-me" `
  -H "Content-Type: application/json" `
  -d "{\"url\":\"https://www.youtube.com/watch?v=VIDEO_ID\"}"
```

Enqueue (CLI, synchronous):

```powershell
python -m lones_vdl enqueue --sync "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Web UI (dev)

Prefer `scripts\dev.ps1` (above). Manual:

```powershell
# Terminal 1
python -m lones_vdl serve

# Terminal 2 — proxies /api to :8080
cd web
npm run dev
```

Open `http://127.0.0.1:5173`, enter your `LONES_VDL_API_TOKEN`, browse the library.
AV1+Opus archives remux to WebM on first play (original untouched).

## Verification

```powershell
powershell -File scripts\check.ps1
```

Or: `make check` (if `make` is available).

## Docker (Linux target)

Compose skeleton under `deploy/`. Intended for the headless host with a NAS bind-mount.
Not required for day-to-day Windows development.

```bash
cd deploy
cp ../.env.example .env   # edit paths/token
docker compose up --build
```

## Roadmap (high level)

1. Core YouTube single-video archive path (API + sidecars + SQLite) — done
2. Web library + remux-only playback — done
3. Web job control — done
4. Integrity rescan/verify — done
5. ~~Desktop client~~ — cancelled (LAN/VPN web UI only)
6. View|Download browse + channel avatars — done
7. Playlist/channel expand + channel watch + delete entry — done
8. Twitch VODs/clips + creator hub — done
9. Headless Linux/Docker deploy + NAS bind-mount — next

Enqueue accepts YouTube video/playlist/channel and Twitch VOD/clip/channel URLs. Channel “Watch” re-lists YouTube uploads or Twitch VOD archives on an interval (`LONES_VDL_CHANNEL_WATCH_INTERVAL_HOURS`) and via **Check watched now** (Twitch clips stay manual). Library filters: platform, content kind (`video` / `vod` / `clip`), and `platform:channel_id` channel keys. Creator hub links channels across sites for related/up-next. Downloads are media-first; English subs are best-effort. Prefer a yt-dlp build with `curl_cffi` impersonation on the host. Cookie filter defaults include youtube + twitch.

**Next session leftovers:** optional View channel-bar polish; confirm curl_cffi/official yt-dlp on the download host; Linux/Docker + NAS deploy.

**Manual smoke:** YouTube playlist or channel; one Twitch VOD + one clip; Twitch channel watch; link YT+Twitch under one creator and confirm related crosses sites.

CLI: `python -m lones_vdl verify` · `python -m lones_vdl rescan`

## License

Proprietary / private unless otherwise stated.
