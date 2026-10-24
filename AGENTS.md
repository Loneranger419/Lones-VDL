# AGENTS.md — Lones-VDL v2

Rules and conventions for humans and coding agents working in this repo. Follow the global user
rules; do not duplicate them here. The plan and its status live in `PLAN.md`; usage and API in
`README.md`. v1 is preserved on the `v1` branch.

## Purpose

Self-hosted archival service: download and preserve videos + metadata with yt-dlp, index in
SQLite, browse and watch through a web UI. **YouTube first; Twitch later.** Runs as a Docker
container on a headless Linux host; developed on Windows.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Topology | Modular monolith: one app container (+ optional PO-token sidecar). No Redis/Celery/microservices. |
| Backend | Python 3.12, FastAPI, managed with **uv** (lockfile committed) |
| Database | SQLite on **local** disk (WAL), SQLAlchemy 2.0, Alembic migrations |
| Jobs | Durable job table in SQLite + in-process async worker + scheduler (channel watch) |
| Live updates | Server-Sent Events |
| Downloader | yt-dlp as a **subprocess** (killable, JSON progress template), in its own updatable venv |
| YouTube access | Anonymous first; cookies from accounts when YouTube refuses (see "Download policy"). Deno + yt-dlp-ejs for JS challenges; bgutil PO-token sidecar optional |
| Media | FFmpeg/ffprobe; preserve originals; remux-only derivatives |
| Frontend | SvelteKit (adapter-static SPA) + TypeScript + Tailwind + shadcn-svelte |
| Data fetching | TanStack Query (Svelte) + client/types generated from the backend OpenAPI spec |
| Player | Video.js 10 (`@videojs/html`), isolated in `player.svelte` |
| Auth | Single admin password → HTTP-only session cookie (no IP allowlists, no bearer tokens in UI) |
| Theme | Dark-first with dark/light/system toggle; **blue** primary, sparing red accents |

## Architecture boundaries

| Area | Responsibility |
|------|----------------|
| `ytdlp/` | Build yt-dlp commands, run subprocess, parse progress/JSON, map errors, update yt-dlp. Nothing else. |
| `platforms/` | Per-platform URL parsing/classification (`youtube` now, `twitch` later) behind one interface |
| `jobs/` | Queue, worker lanes, retry, cancel, scheduler for channel watch |
| `storage/` | Archive paths, partial dirs, atomic promote, sidecar JSON, checksums |
| `media/` | ffprobe, remux; never modify archival originals |
| `db/` | Models, session, migrations. Sidecars are the portable source of truth; the DB is rebuildable. |
| `services/` | Business logic (library, downloads, policy, accounts, channels, collections, integrity, …) |
| `api/` | Thin FastAPI routers: validate, call services, return schemas. No business logic. |
| `frontend/` | SvelteKit UI; talks to the API only through the generated client |

**Platform separation is first-class.** Every video/channel row carries `platform` and
`content_kind`. Never hard-code YouTube outside `platforms/youtube` and `ytdlp/`. The UI keeps
platforms distinct so Twitch slots in without redesign.

## Data and paths

```text
<ARCHIVE_ROOT>/                    # NAS share via CIFS on the host; local folder on Windows
  youtube/
    _channels/<channel_id>/avatar.*, banner.*
    <video_id>/
      media.<ext>  metadata.json  info.json  checksums.json  thumbnail.jpg
      subtitles/<lang>.vtt         # only if fetched on request
<DATA_DIR>/                        # local disk / Docker volume — never on the share
  lones_vdl.db
  secrets/accounts/<id>.txt        # one cookie file per account, mode 0600, domain-filtered
  secrets/session.key
  ytdlp/                           # updatable venv: yt-dlp[default] + bgutil plugin
  logs/jobs/<job_id>.log           # full verbose yt-dlp output per job
```

All paths come from config (`LONES_VDL_*`); `pathlib` only; no hard-coded drive letters.

## Download policy (rules the code must keep)

Goal: reduce account exposure and rate-limit trouble. No setting guarantees protection from
account restrictions. Implemented in `services/policy.py`, `services/accounts.py`,
`jobs/worker.py`; design detail in `docs/download-policy-design.md` (local).

- **One video at a time**, one media fragment. Random delay between videos (min/max, clamped to
  15–30 s). Extraction requests are paced (~2 s); 1–2 transient retries on the same session.
- **Anonymous first.** When YouTube refuses (login required, age restriction, bot check) the job
  moves up one tier to the **alternate** account (dedicated, age-verified). Jobs only move up.
- **Personal account only with explicit per-job approval** (members-only content). The job waits
  in `awaiting_approval`; nothing uses personal credentials silently. Listings never use it.
- **HTTP 429 / throttling pauses all YouTube work** with backoff (15m, 30m, 1h, 2h, then 6h) and
  never changes account. Rate limits are detected from yt-dlp's error text (`ytdlp/errors.py`).
- At least 15 s between authenticated attempts. Daily caps over a rolling 24 h window, editable
  in Settings: 50 videos/streams total, 10 using an account (defaults). A download counts when
  it starts downloading, including ones that fail mid-download.
  A job the user approved by hand (`approved_at`) is exempt from the daily total (it still counts
  towards it, and still waits for the account cap, the delay, and any pause).
  `claim_next` looks through the whole queue, a page at a time: held-back videos at the front must
  never hide shorts or approved jobs behind them.
- **Shorts have their own pool**: 100 a day, 5 of them using an account (defaults), so a
  shorts backfill never uses the video caps. A job is a short if its URL is `/shorts/`, it
  came from a channel's shorts tab, or (found out after resolving) it is portrait and brief.
  **Shorts only run while no video or stream is able to run**: a queued video held back only by
  its own daily cap does not count. A short recognised only after resolving goes back to the
  queue without costing an attempt (`Deferred`, outcome `deferred`).
- **Limits are per site.** `GET /api/policy` returns one entry per platform, each with its
  groups (videos, shorts; Twitch clips will be the short-form group), its pause, and its
  anonymous success counts. The UI shows one card per site. Settings holds one section per
  site. Twitch adds its own entry, caps, and pause; nothing is shared between sites.
- Private videos fail as unavailable (manual "retry with account"); deleted/unavailable are not
  retried; transient network errors retry a limited number of times.
- State is in SQLite (`access_attempts`, `jobs.auth_tier`, `app_settings` keys `policy.*`), so
  restarts and rebuilds keep caps, pauses, and the queue. Interrupted attempts still count.
- **Subtitles are not downloaded with a video** (YouTube throttles them separately; the first
  real 429 came from one). The Watch page "Get subtitles" queues a `subtitles` job (listing lane,
  same pause and ladder rules, alternate at most, counted as a listing).
- Fixed constants live in `services/policy.py`; the Settings page edits only the caps and delay
  (`daily_download_cap`, `daily_auth_cap`, `shorts_daily_cap`, `shorts_daily_auth_cap`, and the
  video delay range).

## Accounts and cookies

- Accounts are managed on the Health page (`/api/accounts`): label, role (`alternate` |
  `personal`), enabled, cookies drag-drop/paste, Test button.
- The server filters uploaded cookies to allowed domains (`youtube.com` only), stores them at
  `secrets/accounts/<id>.txt` (0600), and **never returns cookie values** from any endpoint.
  Never log cookie contents. yt-dlp gets a private temp copy, removed afterwards.
- Guidance for users: use a dedicated Google account, export from a private/incognito window,
  and close it immediately so YouTube does not rotate the cookies.
- No automated login, no credential harvesting, no DRM bypass.

## Auth / security

- First-run setup sets the admin password (or `lones-vdl set-password`). Argon2id hash.
- Session: HTTP-only, `SameSite=Strict` cookie, long-lived sliding expiry. Works for `<video>`
  requests, unlike bearer tokens. Login throttling with backoff.
- CSRF: SameSite=Strict + state-changing requests require header `x-lones-vdl: 1`.
- Every API and media route requires a session except login, setup, and health liveness.
- Intended for LAN/VPN use. Do not expose directly to the public internet.
- Secrets (`.env`, cookies, session key) never committed; see `.gitignore` and `.env.example`.

## Verification

- Single entry point: `powershell -File scripts/check.ps1` (Windows) or `scripts/check.sh`.
  Runs ruff, pytest, svelte-check, and the frontend build. Do not claim features work without it.
- PowerShell sessions need a PATH refresh first (uv is installed via winget):
  `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
  [Environment]::GetEnvironmentVariable('Path','User')`.
- Real YouTube downloads are manual and gated; automated tests use `backend/tests/fake_ytdlp.py`
  (behaviour chosen by video id prefix). Never call real YouTube from tests. Keep real requests
  few: the home IP can be rate-limited.
- Docker changes must be verified by building and running in Docker Desktop.
- UI checks in a real browser: use the `ui-check` skill (`.claude/skills/ui-check`).

## Development workflow

1. Develop on Windows: `cd backend; uv run lones-vdl serve --reload` and
   `cd frontend; npm run dev` (Vite proxies `/api` to `127.0.0.1:8080`).
2. Test the production image locally:
   `docker compose -f deploy/compose.yaml -f deploy/compose.dev.yaml up -d --build`
   → http://localhost:8080, dev password `docker-test-pass`. The user prefers this container left
   running. Its data volume holds real cookies, so test destructive changes on a copy of the volume.
3. Promote the same Git revision to the Linux host.
4. Ask before installing dependencies, changing Git remotes, or committing.

## Backend conventions

- Run backend commands from the repo root: `uv run --project backend lones-vdl ...`.
- Schema changes: edit `db/models.py`, then `uv run --project backend lones-vdl db
  make-migration "msg"`; review and rename the file to `NNNN_<slug>.py` with matching
  `revision`. `test_migrations_match_models` fails if models and migrations drift. Migrations run
  with `PRAGMA foreign_keys=OFF` (batch mode rebuilds tables with DROP); ones that add NOT NULL
  columns need a `server_default`.
- Job pipelines (`run` → completion fields, `cleanup`) are dispatched by `Job.kind` in
  `jobs/worker.py`; each kind belongs to a lane. Priorities live in `services/jobs.py`.
  Error kinds and their user-facing messages are fixed per kind in `ytdlp/errors.py`.
- `get_db` commits at request end; routes whose effects must be visible before the response
  (cookies, worker wake-ups, events) call `db.commit()` explicitly first.
- Code that wakes a background loop from a route uses `events.Wakeup` (thread-safe), never a
  bare `asyncio.Event` (sync routes run in a threadpool).
- Tests: `fake_ytdlp.py` records calls to `$FAKE_YTDLP_STATE`; `conftest.py` has helpers
  (`enqueue`, `wait_for_job`, `add_account`, `calls`).
- Scripted file edits on Windows: always pass `encoding="utf-8"`; prefer the Edit tool. Files
  are CRLF in the working tree.
- **Tags and presets.** yt-dlp's `tags` go to `video_tags` (lowercase key + label) when a video is
  indexed (`services/tags.py`); `Video.tags_indexed` marks videos whose `info.json` was read, and
  `tags.backfill` fills older ones at startup. Filter presets (`services/presets.py`) live in
  `app_settings` key `library.presets` and travel with `state export`. `/api/videos?preset=` takes
  an id, `default`, or `none` and defaults to none: only browse views (Home, Library, channel,
  creator) send `default`. Search, collections, Continue watching, and Up next/related never hide
  anything. Tags match exactly, ignoring case; `tag` needs all, `exclude_tag` none.
- `services/state_transfer.py` backs `lones-vdl state export|import` (database state for moving a
  library to another install; excludes accounts, jobs, policy counters, sessions). If you add a
  table, decide whether it belongs in the bundle and update `_LOCAL_TABLES` / the tests.
- Channel artwork lives at `<archive>/<platform>/_channels/<channel_id>/`; rescan skips `_*`.

## Frontend conventions (SvelteKit 3)

- Config lives in `frontend/vite.config.ts` (no `svelte.config.js`). SPA via `adapter-static`
  with `fallback: 'index.html'`; `ssr = false` in the root `+layout.ts`.
- Internal imports use Node subpath imports `#lib/...` (not `$lib`) and must name the file with
  a `.js` extension: `import { Button } from '#lib/components/ui/button/index.js'`.
- Add shadcn-svelte components with `npx shadcn-svelte@1.7.0 add <name>`; run
  `npx svelte-kit sync` first on a fresh checkout.
- Svelte 5 runes only (`$state`, `$derived`, `$effect`, `$props`). Formatting is prettier.
- API access only through `#lib/api/client.js` (`api` + `call()`) and the query factories in
  `#lib/api/queries.js`. After backend schema changes run `npm run api` (regenerates
  `openapi.json` + `schema.d.ts`; a backend test fails if the snapshot is stale). Request bodies
  with server-side defaults are typed as required; wrap partial updates in `Partial<>`.
- Live updates: `#lib/api/events.svelte.js` patches job lists and invalidates query keys;
  download progress lives in `live.progress`, not in the query cache.
- Filters and tabs live in the URL (`goto(url, { replace: true, reset: false })`).
- Chapters and the "most replayed" heatmap are read from `info.json` per request (cached by file
  identity in `services/chapters.py`); the player gets chapters as a `<track kind="chapters">`. Playing a video missing chapters (under 14 days old) or replay data (under 30)
  calls `POST /api/videos/{id}/chapters/check` (a `chapters` listing-lane job, at most every 24 h).
- The player library is only referenced in `#lib/components/app/player.svelte`. The corner mini player
  (`mini-player.svelte`, state in `#lib/mini-player.svelte.ts`) is a second `Player` that the Watch
  page hands the video to in `beforeNavigate`; it is a hand-off from the saved position, not one
  shared element.
- In a component script, declare every `$state`/`let` that an `$effect.pre` (or a function it calls)
  uses *above* that effect: with cached query data (browser back) it runs during setup and a later
  `let` is still uninitialised (this caused the Watch page "500 Internal Error" on back).
- Service worker: `src/service-worker/index.ts` with its own `tsconfig.json`; it never caches
  `/api/`. PWA icons in `static/icons/` come from the logo SVG; keep them in sync with
  `logo.svelte` and `static/favicon.svg`.

## Keeping docs current

Update the docs in the same change as the code, not later:

- `PLAN.md`: the plan, phase status, backlog, and findings. Change it whenever status moves.
- `AGENTS.md`: rules and conventions for working in the repo. Change it when one changes.
- `README.md`: behavior, commands, and API as users see them.
- Before committing, grep these three files for pointers that no longer match (file names, branch
  names, "see X for Y", command names, defaults) and fix them.
- Keep each fact in one place; link to it from the others instead of copying it.

## Out of scope (until decided otherwise)

Live recording, transcoding, multi-user accounts, public-internet exposure, desktop app,
automatic creator matching, Twitch (until Phase 6).
