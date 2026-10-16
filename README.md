# Lones-VDL

Cross-platform (Windows develop → Linux/Docker deploy) video archival system focused on
reliable long-term preservation of YouTube and Twitch content and metadata.

**Status:** Milestone 3 — web enqueue + job queue alongside library playback.

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
4. Integrity rescan/verify
5. ~~Desktop client~~ — cancelled (LAN/VPN web UI only)

## License

Proprietary / private unless otherwise stated.
