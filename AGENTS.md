# AGENTS.md — Lones-VDL v2

Project-specific instructions and rewrite plan for humans and coding agents.
Follow global user rules; do not duplicate them here.

> **Status:** v2 clean rewrite in progress. v1 is preserved on the `v1` branch.
> This file supersedes `docs/architecture.md` (v1), which is removed in Phase 1.

## Purpose

Self-hosted archival service: download and preserve videos + metadata with yt-dlp, index in
SQLite, browse and watch through a polished web UI. **YouTube first; Twitch added later.**
Runs as a Docker container on a headless Linux VM; developed on Windows.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Topology | Modular monolith: one app container + PO-token sidecar. No Redis/Celery/microservices. |
| Backend | Python 3.12, FastAPI, managed with **uv** (lockfile committed) |
| Database | SQLite on **local** disk, SQLAlchemy 2.0 models, Alembic migrations |
| Jobs | Durable job table in SQLite + in-process async worker + scheduler (channel watch) |
| Live updates | Server-Sent Events (download progress, job state) |
| Downloader | yt-dlp as a **subprocess** (killable, JSON progress template), in its own updatable venv |
| YouTube anti-bot | Cookies (required) + Deno/yt-dlp-ejs (JS challenges); bgutil PO-token sidecar optional |
| Media | FFmpeg/ffprobe; preserve originals; remux-only derivatives |
| Frontend | SvelteKit (adapter-static, SPA) + TypeScript + Tailwind + shadcn-svelte |
| Data fetching | TanStack Query (Svelte) + client/types generated from the backend OpenAPI spec |
| Player | Vidstack |
| Auth | Single admin password → HTTP-only session cookie (no IP allowlists, no bearer tokens in UI) |
| Theme | Dark-first with dark/light/system toggle; **blue** primary, sparing red accents |
| Existing data | None kept — fresh archive layout and DB |

## Architecture boundaries

| Area | Responsibility |
|------|----------------|
| `ytdlp/` | Build yt-dlp commands, run subprocess, parse progress/JSON, map errors, update yt-dlp. Nothing else. |
| `platforms/` | Per-platform URL parsing/classification (`youtube` now, `twitch` later) behind one interface |
| `jobs/` | Queue, worker, concurrency, retry, cancel, scheduler for channel watch |
| `storage/` | Archive paths, partial dirs, atomic promote, sidecar JSON, checksums |
| `media/` | ffprobe, remux; never modify archival originals |
| `db/` | Models, session, migrations. Sidecars remain the portable source of truth; DB is rebuildable. |
| `services/` | Business logic (library, downloads, channels, collections, progress, integrity, cookies) |
| `api/` | Thin FastAPI routers: validate, call services, return schemas. No business logic. |
| `frontend/` | SvelteKit UI; talks to the API only through the generated client |

**Platform separation is a first-class concept.** Every video/channel row carries `platform`
and `content_kind`. Build YouTube only, but never hard-code YouTube outside `platforms/youtube`
and `ytdlp/`. The UI keeps platforms distinct (platform switcher/sections in library, channel
pages, search filters) so Twitch slots in without redesign.

## Repository layout (target)

```text
backend/
  pyproject.toml, uv.lock
  src/lones_vdl/
    main.py            # app factory, lifespan (worker + scheduler start/stop)
    config.py          # pydantic-settings, LONES_VDL_* env
    api/               # routers: auth, videos, channels, creators, collections, progress,
                       #          jobs, events (SSE), cookies, health, settings, media
    services/
    platforms/         # base.py, youtube.py (twitch.py later)
    ytdlp/             # runner.py, errors.py, updater.py
    jobs/              # worker.py, scheduler.py
    db/                # models.py, session.py, migrations/
    storage/
    media/
    cli.py             # serve, doctor, rescan, set-password
  tests/
frontend/              # SvelteKit app (src/routes, src/lib/components, src/lib/api); build/ output
deploy/
  Dockerfile           # multi-stage: frontend build → python runtime
  compose.yaml         # production (VM): app + bgutil-pot sidecar
  compose.dev.yaml     # override for local Docker Desktop testing
  entrypoint.sh        # chown /data, drop to PUID:PGID
  vm/                  # VM boot helpers (CIFS mount retries, status report)
  .env.example
scripts/
  check.ps1, check.sh  # single verification entry point
```

## Data and paths

```text
<ARCHIVE_ROOT>/                    # NAS share via CIFS on the VM; local folder on Windows
  youtube/
    _channels/<channel_id>/avatar.*, banner.*
    <video_id>/
      media.<ext>
      metadata.json                # yt-dlp info + archive provenance (platform, content_kind)
      thumbnails/  subtitles/  checksums.json  derivatives/
<DATA_DIR>/                        # local disk / Docker volume — never on the share
  lones_vdl.db
  secrets/cookies.txt              # mode 0600, filtered to allowed domains
  secrets/session.key
  ytdlp/                           # updatable venv: yt-dlp[default] + bgutil plugin
  logs/jobs/<job_id>.log           # full verbose yt-dlp output per job
```

- All paths from config; `pathlib` only; no hard-coded drive letters.
- SQLite must stay on local disk (WAL mode).

## Features (v2 scope)

- **Library:** grid with search, filters (platform, channel, kind, watched state), sort.
- **Watch:** Vidstack player, captions, resume from saved position, auto-mark watched (~90%),
  up next (same channel / collection), related via creator hub.
- **Watch progress & markers:** per-video position + watched flag; "Continue watching" on Home.
- **Collections:** in-app playlists, user-ordered, independent of YouTube playlists.
- **Downloads:** paste video / playlist / channel URL, quality choice, live SSE progress,
  cancel, retry, failed jobs show classified error + full log. Duplicate detection.
- **Channel watch:** per-channel auto-archive toggle, interval, "check now".
- **Creator hub:** manual linking of channels across platforms (no auto-match).
- **Health:** integrity verify/rescan, storage stats, yt-dlp version + update, cookie status,
  diagnostics (`doctor`) with verbose test against any URL.
- **Settings:** non-secret runtime settings (concurrency, default quality, watch interval,
  yt-dlp channel stable/nightly).

### Pages

Home · Library · Watch · Channels / Creators · Collections · Downloads · Health · Settings · Login.
Desktop: collapsible sidebar. Phone: bottom navigation. Installable as a PWA. Every view has a
real URL (back button, bookmarks, deep links).

## yt-dlp reliability (Docker)

The v1 container failed on age-gated videos that worked on Windows. Root cause unconfirmed
(stale yt-dlp in the image, rotated/expired cookies, missing PO tokens, or VM network). v2 design:

1. yt-dlp installed into `<DATA_DIR>/ytdlp` venv, not baked into the image. Daily auto-update
   + "Update now" in Health. Version recorded on every job.
2. Deno and FFmpeg in the image; bgutil PO-token provider as a compose sidecar.
3. Every job writes a full `-v` log; UI shows the classified error and the raw log.
4. `lones-vdl doctor` (CLI + Health page): versions, Deno/FFmpeg/plugin presence, PO provider
   reachable, cookie file validity and expiry, verbose test download of a given URL.
5. Non-root container user with `PUID`/`PGID` to avoid CIFS permission issues.

## Cookies (required for age-gated content)

- "YouTube access" page: drag-drop or paste `cookies.txt`. Server filters to allowed domains,
  stores at `secrets/cookies.txt` (0600), and **never returns cookie values** from any endpoint.
- Status: domains present, earliest auth-cookie expiry, last successful test; **Test** button
  checks against an age-restricted video.
- In-page guidance: use a dedicated Google account (age-verified); export from a private/incognito
  window and close it immediately so YouTube does not rotate the cookies.
- No automated login, no credential harvesting, no DRM bypass. Never log cookie contents.

## Auth / security

- First-run setup screen sets the admin password (or `lones-vdl set-password`). Argon2id hash.
- Session: HTTP-only, `SameSite=Strict` cookie, long-lived sliding expiry ("remember this device").
  Works for `<video>` media requests, unlike bearer tokens.
- Login throttling: exponential backoff / temporary lockout after repeated failures.
- CSRF: SameSite=Strict + state-changing requests require JSON / custom header.
- Every API and media route requires a session except login, setup, and health liveness.
- Intended for LAN/VPN use. Do not expose directly to the public internet.
- Secrets (`.env`, cookies, session key) never committed; see `.gitignore` and `.env.example`.

## Phases

- [x] **0. Diagnose v1 Docker failure.** Done 2026-10-22 — see "Phase 0 findings" below.
- [x] **1. Skeleton.** Done 2026-10-22. v1 code removed (kept on `v1`). uv backend with health
      route, SPA serving, CLI (`serve`, `cookies`); SvelteKit 3 + Tailwind 4 + shadcn-svelte
      (Nova preset); `scripts/check.*`; Dockerfile + compose verified healthy in Docker Desktop
      (non-root via PUID/PGID, Deno + FFmpeg present).
- [ ] **2. Backend core.** Config, DB models + first migration, auth, storage, yt-dlp runner +
      updater, job worker, SSE, single-video download end to end, `doctor`.
- [ ] **3. Backend features.** Playlists/channels expand, channel watch scheduler, creator hub,
      collections, watch progress, integrity verify/rescan, cookies API, media streaming (range).
- [ ] **4. Frontend.** Design tokens + theme toggle, app shell (sidebar/bottom nav), login/setup,
      then pages in order: Downloads → Library → Watch → Channels → Home → Collections → Health →
      Settings. PWA manifest.
- [ ] **5. Deploy.** Compose on the Linux VM with CIFS archive mount; verify age-gated download
      with cookies; document the runbook in `README.md`.
- [ ] **6. Twitch.** `platforms/twitch.py`, VODs/clips, Twitch sections in the UI.

### Phase 0 findings (2026-10-22)

Tested the v1 image (yt-dlp 2026.10.21, Deno 2.9.7, yt-dlp-ejs 0.8.0, no PO-token provider) in
Docker Desktop against Windows yt-dlp 2026.08.19 / 2026.03.17, same home IP.

- **Without cookies, everything fails on both OSes** — even public videos get
  "Sign in to confirm you're not a bot" (LOGIN_REQUIRED). Not a Linux/Docker problem.
- **With valid cookies, Docker works fully:** public and age-restricted videos resolve, and a
  real download of an age-restricted video (1080p AV1 + Opus, merged, ffprobe OK) succeeded
  with no 403s. PO tokens were not needed.
- Likely v1 causes: missing/expired/rotated cookies in the container, and/or the VM running an
  image built before Deno + yt-dlp-ejs were added (commit `7abc000`).

Design consequences:

- Cookies are **required for all YouTube downloads**, not just age-gated ones. Missing or failing
  cookies must be a loud, top-level status in the UI, and jobs should fail fast with that reason.
- Browser exporters produce **full-browser jars** (banking, shopping, AI sites). Import must keep
  only allowed domains and discard the rest. **`youtube.com` alone is sufficient** (verified with
  an age-restricted download); do not keep `google.com` cookies (Gmail/Drive/etc.). `twitch.tv`
  later.
- v1's filter treated `#HttpOnly_` rows as comments and dropped YouTube's login cookies.
- Current tool: `scripts/cookie_filter.py` (stdlib only, tested). Move its pure functions into
  the backend cookie import service in Phase 2/3.
- Some exporters write Chrome/WebKit timestamps (µs since 1601) instead of Unix seconds. Import
  must normalize expiry so status/expiry reporting is correct.
- yt-dlp writes cookies back to its `--cookies` file; the app owns that file, so that's fine,
  but never point yt-dlp at an operator's original export.
- Deno + yt-dlp-ejs are essential. The bgutil PO-token sidecar is **optional** (add to compose as
  an opt-in profile; enable if 403s/bot checks return with cookies).

## Verification

Single entry point (created in Phase 1):

- Windows: `powershell -File scripts/check.ps1`
- Linux: `scripts/check.sh`

Runs ruff, pytest, svelte-check, and the frontend build. Do not claim features work without
running checks. Real YouTube downloads are manual/gated — mock the yt-dlp subprocess in
automated tests. Docker changes must be verified by building and running in Docker Desktop.

## Development workflow

1. Develop on Windows: `cd backend; uv run lones-vdl serve --reload` and
   `cd frontend; npm run dev` (Vite proxies `/api` to `127.0.0.1:8080`).
2. Test the production image locally:
   `docker compose -f deploy/compose.yaml -f deploy/compose.dev.yaml up --build`.
3. Promote the same Git revision to the Linux VM.
4. Ask before installing dependencies, changing Git remotes, or committing.

## Frontend conventions (SvelteKit 3)

- Config lives in `frontend/vite.config.ts` (no `svelte.config.js`). SPA via
  `adapter-static` with `fallback: 'index.html'`; `ssr = false` in the root `+layout.ts`.
- Internal imports use Node subpath imports `#lib/...` (not `$lib`) and must name the file
  with a `.js` extension: `import { Button } from '#lib/components/ui/button/index.js'`.
- Add shadcn-svelte components with `npx shadcn-svelte@1.7.0 add <name>`; run
  `npx svelte-kit sync` first on a fresh checkout (it generates `node_modules/$app/tsconfig`).
- Svelte 5 runes only (`$state`, `$derived`, `$effect`, `$props`). Formatting is prettier.

## Out of scope (until decided otherwise)

Live recording, transcoding, multi-user accounts, public-internet exposure, desktop app,
automatic creator matching, Twitch (until Phase 6).
