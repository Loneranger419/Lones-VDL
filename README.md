# Lones-VDL

Self-hosted YouTube archive: download with yt-dlp, preserve media and metadata, browse and
watch in a web UI. Runs in Docker on a Linux VM; developed on Windows.

> v2 rewrite in progress. See [AGENTS.md](AGENTS.md) for the plan and current phase.
> The previous version lives on the `v1` branch.

## Layout

| Path | What |
|------|------|
| `backend/` | Python 3.12 + FastAPI, managed with [uv](https://docs.astral.sh/uv/) |
| `frontend/` | SvelteKit (static SPA) + Tailwind + shadcn-svelte |
| `deploy/` | Dockerfile, compose files, VM helper scripts |
| `scripts/` | `check.ps1` / `check.sh` — the single verification entry point |

## Develop (Windows)

Requires uv, Node 22, and Docker Desktop (for image testing).

```powershell
# backend API on http://127.0.0.1:8080 (auto-reload)
cd backend; uv run lones-vdl serve --reload

# frontend dev server on http://localhost:5173 (proxies /api to the backend)
cd frontend; npm install; npm run dev
```

Optional: copy `.env.example` to `.env` at the repo root to change paths and ports.

## Verify

```powershell
powershell -File scripts/check.ps1
```

Runs ruff, pytest, prettier, svelte-check, and the frontend build.

## Test the production image locally

```powershell
docker compose -f deploy/compose.yaml -f deploy/compose.dev.yaml up --build
# open http://localhost:8080 ; stop with: docker compose -f deploy/compose.yaml -f deploy/compose.dev.yaml down
```

## Deploy (Linux VM)

```bash
cp deploy/.env.example deploy/.env   # set LONES_VDL_HOST_ARCHIVE, PUID/PGID
docker compose -f deploy/compose.yaml up -d --build
```

## Cookies

YouTube currently requires signed-in cookies for downloads. Export `cookies.txt` from a
private browser window (then close it), and filter it to YouTube-only before use:

```powershell
cd backend; uv run lones-vdl cookies ..\secrets\cookies.txt --replace
```

The filter keeps only `youtube.com` cookies and never prints cookie values. Never commit
cookie files.
