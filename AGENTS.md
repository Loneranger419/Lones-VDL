# AGENTS.md — Lones-VDL v2

Project-specific instructions and rewrite plan for humans and coding agents.
Follow global user rules; do not duplicate them here.

> **Status:** v2 rewrite, Phases 0–4 done; Phase 5 (VM deploy) next — see "Resume here". v1 is preserved on the `v1` branch.
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
| Player | Video.js 10 (`@videojs/html`, packaged video skin), isolated in `player.svelte` |
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
- **Watch:** Video.js player, captions, resume from saved position, auto-mark watched (~90%),
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
- [x] **2. Backend core.** Done 2026-10-22. Live-verified in Docker with private-window
      cookies: age-restricted 720p (AV1+Opus webm) and public video archived, checksums OK.
      SQLAlchemy models + Alembic `0001`; password/session auth with throttle + CSRF header
      (`x-lones-vdl: 1`); managed yt-dlp venv with auto-install/update; durable job queue with
      retry/backoff/cancel/restart recovery; SSE `/api/events`; storage with atomic promote,
      sidecar, checksums; `doctor`, `cookies import`, `set-password`, `ytdlp update` CLI.
      Verified in Docker: auto-install, real yt-dlp error classification (`cookies_missing`).
- [x] **3. Backend features.** Done 2026-10-22. Migration `0002`. Playlist/channel URLs become
      `expand` jobs (modes all/recent/baseline/meta; tabs videos/streams/shorts; live and
      upcoming skipped) that queue child downloads by priority. Channel auto-archive with
      scheduler + "check now"; channel avatar/banner. Worker lanes: downloads (runtime
      concurrency), listing (1), maintenance (1). Library query API (search/filter/sort/page),
      related/up next, watch progress (90% = watched), continue watching, delete (→ ignored),
      collections, creators, media/thumbnail/subtitle streaming with Range, verify/rescan
      (rescan also relinks lost channel links), stats, cookies API (raw-text upload, status
      without values, test, delete, health, auto-requeue of cookie failures), runtime settings
      API. Live-verified in Docker: channel + uploads-playlist listing, artwork, Range, verify.
- [x] **4. Frontend.** Done 2026-10-22. All pages (Home, Library, Watch, Channels/Creators,
      Collections, Downloads, Health, Settings, Login/setup), sidebar + phone bottom nav, dark/light
      theme, live SSE updates, OpenAPI-generated client, PWA manifest + icons + service worker.
      Vidstack turned out to be deprecated (security-only until 2028); switched to Video.js 10.
      Verified in Docker with headless Edge: pages at desktop/phone widths, playback progress
      saving, resume, auto-watched at the end, collections, add dialog.
- [ ] **5. Deploy.** Compose on the Linux VM with CIFS archive mount; verify age-gated download
      with cookies; document the runbook in `README.md`.
- [ ] **6. Twitch.** `platforms/twitch.py`, VODs/clips, Twitch sections in the UI.

### Resume here (state at end of Phase 4, 2026-10-22)

Everything through Phase 4 is committed on `main` (originally `c9bdccb` on the old `v2` branch, now deleted). The user has tried the UI
and reported no bugs. Next step: **Phase 5**, but start it only after the user asks.

**Phase 5 plan:**

1. Start from `deploy/compose.yaml` + `deploy/.env.example`. Set `LONES_VDL_HOST_ARCHIVE` to the
   CIFS mount, and `PUID`/`PGID` to the share owner.
2. Reuse `deploy/vm/fix-vm-mount-boot.sh` (CIFS mount retries at boot) and `host-status.sh`
   (status report). Review them; they come from v1.
3. Promote the same Git revision to the VM. Import private-window cookies via Health. Verify:
   - an age-gated download;
   - Range playback from the share;
   - verify/rescan on CIFS.
4. **HTTPS for PWA install:** service workers and "install app" need a secure context. Plain
   `http://<vm-ip>:8080` works but cannot be installed. The user has Tailscale on Windows, so
   `tailscale serve` (or a reverse proxy) is the likely route. Ask before choosing.
5. Write the VM runbook in `README.md`: first-run password, cookies, updates, backups of
   `<DATA_DIR>`.

**Backlog (agreed or noticed, not scheduled):**

- Per-download "compatible" H.264 option (remux/derivative, never touching the original).
- Platform filter in the library and search. The API has no `platform` query param yet; add it
  with Twitch at the latest.
- `npm audit`: 5 low-severity warnings from an old `@sveltejs/kit`/`cookie` nested inside
  `bits-ui`. That code is server-side only and unused by the SPA. Recheck when `bits-ui` updates.
- Autoplay on arrival at the Watch page is untested in a real browser (headless blocks it).
- Video.js 10 is new (10.0.1, pinned). Consider upgrading after it matures; only
  `player.svelte` uses it.
- **Chapters and key moments.** Import chapters that creators put in a video's description or
  metadata (yt-dlp exposes them as `chapters` in `metadata.json`). Show them as a clickable list on
  the Watch page and as markers on the player's timeline. Also import "most replayed" / popular
  sections when yt-dlp or the video data provides them, and show them the same way. Keep this
  per-video and optional: videos without chapters must work as they do now.

**Local test environment (Windows):**

- Docker test container:
  - Run `docker compose -f deploy/compose.yaml -f deploy/compose.dev.yaml up -d --build`.
  - Open http://localhost:8080. The dev password is `docker-test-pass`.
  - It holds two archived test videos (ids 1, 2) and real cookies in its data volume.
  - The user prefers it left running.
- PowerShell sessions need a PATH refresh before `scripts/check.ps1` (uv is installed via
  winget): `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
  [Environment]::GetEnvironmentVariable('Path','User')`.
- No Playwright here. UI checks drive headless Edge over the DevTools protocol, with Python
  `websocket-client` (already installed system-wide):
  - Start with `msedge --headless=new --remote-debugging-port=9333 --user-data-dir=<tmp>`.
  - Connect with `suppress_origin=True`.
  - Open a fresh tab per page via `PUT /json/new`. Reusing one tab across navigations stalled.
  - Log in through `POST /api/auth/login`, then `Network.setCookie`.
  - In Git Bash, set `MSYS_NO_PATHCONV=1` so `/library`-style arguments aren't rewritten.

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

## Backend conventions

- Run backend commands from the repo root: `uv run --project backend lones-vdl ...`.
- Schema changes: edit `db/models.py`, then `uv run --project backend lones-vdl db
  make-migration "msg"`; review and rename the file to `NNNN_<slug>.py` with matching
  `revision`. `test_migrations_match_models` fails if models and migrations drift.
- Tests drive the real subprocess path with `backend/tests/fake_ytdlp.py` (behaviour chosen by
  video id prefix). Never call real YouTube from automated tests.
- `get_db` commits at request end; routes whose effects must be visible before the response
  (cookies, worker wake-ups, events) call `db.commit()` explicitly first.
- State-changing API requests require header `x-lones-vdl: 1` (CSRF guard).
- Scripted file edits on Windows: always pass `encoding="utf-8"`; prefer the Edit tool.
- Migrations run with `PRAGMA foreign_keys=OFF` (see `migrations/env.py`): batch mode rebuilds
  tables with DROP, which would otherwise fire `ON DELETE SET NULL` on child rows. Migrations
  that add NOT NULL columns need a `server_default` for existing rows.
- Job pipelines (`run` → completion fields, `cleanup`) are dispatched by `Job.kind` in
  `jobs/worker.py`; each kind belongs to a lane. Priorities live in `services/jobs.py`.
- Code that wakes a background loop from a route uses `events.Wakeup` (thread-safe), never a
  bare `asyncio.Event` (sync routes run in a threadpool).
- Channel artwork lives at `<archive>/<platform>/_channels/<channel_id>/`; rescan skips `_*`.

## Frontend conventions (SvelteKit 3)

- Config lives in `frontend/vite.config.ts` (no `svelte.config.js`). SPA via
  `adapter-static` with `fallback: 'index.html'`; `ssr = false` in the root `+layout.ts`.
- Internal imports use Node subpath imports `#lib/...` (not `$lib`) and must name the file
  with a `.js` extension: `import { Button } from '#lib/components/ui/button/index.js'`.
- Add shadcn-svelte components with `npx shadcn-svelte@1.7.0 add <name>`; run
  `npx svelte-kit sync` first on a fresh checkout (it generates `node_modules/$app/tsconfig`).
- Svelte 5 runes only (`$state`, `$derived`, `$effect`, `$props`). Formatting is prettier.
- API access only through `#lib/api/client.js` (`api` + `call()`) and the query factories in
  `#lib/api/queries.js`. After backend schema changes run `npm run api` (regenerates
  `openapi.json` + `schema.d.ts`; a backend test fails if the snapshot is stale). Request
  bodies with server-side defaults are typed as required; wrap partial updates in `Partial<>`.
- Live updates: `#lib/api/events.svelte.js` patches job lists and invalidates query keys;
  download progress lives in `live.progress`, not in the query cache.
- Filters and tabs live in the URL (`goto(url, { replace: true, reset: false })`; SvelteKit 3
  renamed `replaceState`/`noScroll`/`keepFocus`).
- The player library is only referenced in `#lib/components/app/player.svelte`.
- Service worker: `src/service-worker/index.ts` with its own `tsconfig.json` (uses
  `$app/manifest`, `$app/env`, `$app/service-worker`); it never caches `/api/`.
- PWA icons in `static/icons/` were rendered from the logo SVG; keep them in sync with
  `logo.svelte` and `static/favicon.svg` if the logo changes.

## Out of scope (until decided otherwise)

Live recording, transcoding, multi-user accounts, public-internet exposure, desktop app,
automatic creator matching, Twitch (until Phase 6).
