# Lones-VDL

Cross-platform (Windows develop → Linux/Docker deploy) video archival system focused on
reliable long-term preservation of YouTube and Twitch content and metadata.

**Status:** YouTube singles + View/Download browse; playlists/channel expand + channel watch.

## Architecture

See [docs/architecture.md](docs/architecture.md) and [AGENTS.md](AGENTS.md).

## Requirements (development)

- Python 3.11+
- (Later) yt-dlp, FFmpeg on PATH or via Docker image
- Node.js 20+ when building the web UI (placeholder present; not required for API smoke tests)

## Quick start (Windows)

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

Terminal 1 — API:

```powershell
python -m lones_vdl serve
```

Terminal 2 — UI (proxies `/api` to `:8080`):

```powershell
cd web
npm run dev
```

Open the Vite URL, enter your `LONES_VDL_API_TOKEN`, browse the library.
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
8. Twitch archival — next
9. Headless Linux/Docker deploy + NAS bind-mount — last

Enqueue accepts video, playlist, or channel URLs. Channel “Watch” re-lists uploads on an interval (`LONES_VDL_CHANNEL_WATCH_INTERVAL_HOURS`) and via **Check watched now**. Downloads are media-first; English subs are best-effort (subtitle 429s do not fail the job). Prefer a yt-dlp build with `curl_cffi` impersonation on the host.

**Next session leftovers:** optional View channel-bar polish; confirm curl_cffi/official yt-dlp on the machine that runs playlists; Twitch then deploy.

**Manual smoke:** paste a small playlist (or an unlisted one you create with short clips such as [Me at the zoo](https://www.youtube.com/watch?v=jNQXAC9IVRw)), and a channel you control with few uploads for watch testing.

CLI: `python -m lones_vdl verify` · `python -m lones_vdl rescan`

## License

Proprietary / private unless otherwise stated.
