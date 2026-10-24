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

Requires uv, Node 22, and Docker Desktop (for image testing). Run backend commands from the
repo root so `./data` and `.env` resolve there.

```powershell
# backend API on http://127.0.0.1:8080 (auto-reload); installs yt-dlp into data/ytdlp on start
uv run --project backend lones-vdl serve --reload

# frontend dev server on http://localhost:5173 (proxies /api to the backend)
cd frontend; npm install; npm run dev

# environment check (add --url <video> to test a real resolve)
uv run --project backend lones-vdl doctor
```

Optional: copy `.env.example` to `.env` at the repo root to change paths and ports.
On first open, the UI (or `lones-vdl set-password`) asks you to choose the admin password.

## Verify

```powershell
powershell -File scripts/check.ps1
```

Runs ruff, pytest, prettier, svelte-check, and the frontend build.

After changing a backend route or schema, regenerate the frontend API client (the OpenAPI
snapshot test fails until you do):

```powershell
cd frontend; npm run api
```

## Using the app

| Page | What it's for |
|------|---------------|
| Home | Continue watching, downloads in progress, recently archived, channels |
| Library | Everything archived: search (top bar), kind / progress / channel filters, sort |
| Watch | Player with captions (not downloaded with a video; "Get subtitles" fetches them as a small job) and resume; marks a video watched at 90%; up next with autoplay; collection playlists via `?collection=` |
| Downloads | Paste a video, playlist, or channel link; live progress, cancel, retry (optionally with an account), approve personal-account videos, full yt-dlp log per job |
| Channels | Per-channel auto-archive (what to include, quality, "Check now"), creator linking; Creators tab groups channels |
| Collections | Your own ordered playlists |
| Health | YouTube accounts (drop a `cookies.txt` per account, test it), download limits, yt-dlp version and update, storage, verify / rescan, diagnostics |
| Settings | Theme, default quality, daily download limits, delay between videos, check intervals, password |

On a phone the sidebar becomes a bottom bar. The app can be installed to a home screen, but
browsers only allow that (and the offline app shell) over HTTPS or on `localhost`; over plain
`http://<vm-ip>:8080` everything else works, there is just no install prompt.

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

## Accounts and download policy

Downloads run one video at a time, with a random 15-30 s pause between videos, and try
**without an account first**. If YouTube refuses (login required, age restriction, bot check),
the job moves to the **alternate** account (a dedicated, age-verified Google account). A
**personal** account is never used on its own: a video that needs it (for example members-only)
waits under Downloads > "Needs approval" until you approve it. Rate limits (HTTP 429) pause the
queue with a backoff and never switch accounts. Daily caps (default 50 videos, 10 using an
account, rolling 24 hours) and the delay range are in Settings. These are starting points; no
setting guarantees YouTube will not restrict an account.

Add accounts and their cookies on the Health page. To export cookies, so YouTube does not
rotate them:

1. Open a **private/incognito** window, sign in to YouTube, play any video.
2. Export `cookies.txt` with your exporter extension.
3. **Close the private window** without logging out.
4. Import (keeps only `youtube.com` cookies, stored readable only by the app):

```powershell
# local development
uv run --project backend lones-vdl cookies import path	o\cookies.txt --account Alternate --delete-source

# into the Docker container (piped, so no copy is left inside the container)
Get-Content -Raw path	o\cookies.txt | docker compose -f deploy/compose.yaml exec -T lones-vdl lones-vdl cookies import - --account Alternate
```

`--account LABEL` creates the account if needed; add `--role personal` for a personal one
(default `alternate`). The web UI uses `POST /api/accounts/{id}/cookies` with the file as a
plain-text body. Importing new cookies retries jobs that failed because of cookies.

Then confirm with the Test button, or `lones-vdl doctor --url https://www.youtube.com/watch?v=<id>`.
Cookie values are never printed, logged, or returned by the API. Never commit cookie files.

## Move a library to another install

The archive folder holds the videos and a sidecar for each one, so copying it is enough to
bring the videos over. The database also holds watch progress, collections, creators, and
channel auto-archive settings; `state export` / `state import` carry those.

1. **On the old install** (the app may keep running):

   ```powershell
   docker compose -f deploy/compose.yaml -f deploy/compose.dev.yaml exec lones-vdl lones-vdl state export /tmp/state.zip
   docker cp <container>:/tmp/state.zip .
   ```

2. **Copy the archive folder** to the new host's archive location (the NAS share).
3. **On the new host**, stop the app, then import into its data volume. The bundle is mounted
   read-only into a one-off container:

   ```bash
   docker compose -f deploy/compose.yaml run --rm -v "$PWD:/in:ro" lones-vdl lones-vdl state import /in/state.zip
   docker compose -f deploy/compose.yaml up -d
   ```

   It refuses to overwrite an install that already has a library unless you add `--replace`
   (the old database is kept as `lones_vdl.db.before-import-<time>`).
4. In the app: add the account cookies on the Health page, then run **Rescan** (flags videos whose
   files are missing, indexes any extra folders) and **Verify** (checks every file against its
   checksums).

Not carried over, on purpose: accounts and cookies (export fresh ones; reusing a session from two
places can get it flagged), the job queue and history, download-limit counters and any pause, and
login sessions. The bundle contains the admin password hash unless you pass `--no-password`; keep
it private.

## API

Interactive docs at `http://<host>:8080/docs`. Calls need a signed-in session (log in through
the app in the same browser), and state-changing calls need the header `x-lones-vdl: 1`.
Main areas:

| Area | Endpoints |
|------|-----------|
| Downloads | `POST /api/jobs` with a video, playlist, or channel URL; `POST /api/videos/{id}/subtitles` fetches captions later (`watch`, `backfill`, `tabs` for channels); list/cancel/retry/log |
| Library | `GET /api/videos` (search, filters, sort, paging), `/continue`, `/{id}/related`, progress, watched, delete |
| Media | `/api/videos/{id}/media` (Range), `/thumbnail`, `/subtitles/{lang}.vtt`, `/api/channels/{id}/avatar` |
| Channels | list, details, `PATCH` watch settings, `POST /{id}/check` |
| Creators, collections | CRUD; collections keep a user-defined order |
| Health | `/api/system/doctor`, `/stats`, `POST /verify`, `POST /rescan`, yt-dlp status/update |
| Settings | `GET/PATCH /api/settings` (quality, daily caps, video delay, watch interval, yt-dlp channel); `/api/accounts`, `/api/policy` |
| Live updates | `GET /api/events` (Server-Sent Events) |
