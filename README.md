# Lones-VDL

Cross-platform (Windows develop → Linux/Docker deploy) video archival system focused on
reliable long-term preservation of YouTube and Twitch content and metadata.

**Status:** Milestone 0 scaffold — health API and verification only. No downloads yet.

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
python -m lones_vdl
```

Health check: `GET http://127.0.0.1:8080/api/health`

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

1. Core YouTube single-video archive path (API + sidecars + SQLite)
2. Web library + remux-only playback
3. Web job control
4. Integrity rescan/verify
5. Thin desktop client

## License

Proprietary / private unless otherwise stated.
