# PLAN.md — Lones-VDL v2

The plan and where it stands. Rules and conventions for working in the code are in `AGENTS.md`;
usage and API are in `README.md`. v1 is preserved on the `v1` branch.

**Current state (2026-10-23):** Phases 0–4 done, plus the YouTube download policy (below).
Everything is committed and pushed to `main`. **Next: Phase 5 (deploy to the LXC/VM) — start only when the user asks.**

## Phases

- [x] **0. Diagnose v1 Docker failure.** 2026-10-22. See "Findings" below.
- [x] **1. Skeleton.** v1 code removed; uv backend, SPA serving, CLI; SvelteKit 3 + Tailwind 4 +
      shadcn-svelte; `scripts/check.*`; Dockerfile + compose verified in Docker Desktop.
- [x] **2. Backend core.** Models + Alembic, password/session auth, managed yt-dlp venv, durable
      job queue (retry/backoff/cancel/restart recovery), SSE, storage with atomic promote,
      sidecar and checksums, `doctor` and CLI.
- [x] **3. Backend features.** Playlist/channel `expand` jobs, channel auto-archive scheduler,
      library query API, watch progress, collections, creators, media streaming with Range,
      verify/rescan, stats, runtime settings.
- [x] **4. Frontend.** All pages, sidebar + phone nav, theme, live SSE updates, generated API
      client, PWA. Vidstack was deprecated, so the player is Video.js 10.
- [x] **Download policy** (2026-10-23, between 4 and 5). Anonymous first, accounts table, daily
      caps, delays, rate-limit pause, approval for the personal account, subtitles on request,
      a separate shorts pool that yields to videos, and per-site limit cards.
      Rules in `AGENTS.md`; design detail in `docs/download-policy-design.md` (local).
- [ ] **5. Deploy.** See below.
- [ ] **6. Twitch.** `platforms/twitch.py`, VODs/clips, Twitch sections in the UI. Clips are the
      short-form group: own caps, wait for VODs, as shorts do. Twitch gets its own entry in
      `GET /api/policy` (own caps and pause), its own limits card, and its own Settings section. Design and defaults: "Phase 6 — Twitch"
      below.

## Phase 5 — deploy

0. **Private network first (Headscale + WireGuard).** Detailed plan in `docs/headscale-setup.md`
   (git-ignored). Summary:
   - A WireGuard VPN is the only way in from outside the home network: the one port opened on
     the router.
   - Headscale runs in a Proxmox LXC (Debian 13). It is the control server for a Tailscale mesh
     (issues device keys, keeps peers up to date); it is not the VPN itself.
   - Its HTTPS name resolves only to a private LAN address. Caddy gets the certificate through
     Cloudflare DNS validation, so the server never needs to be reachable from the internet.
   - A web UI manages users and devices (Headplane is the candidate; verify it is maintained).
   - Order: WireGuard first (phones must be on it before they can join), then the LXC, then devices.
   - Open items (router model, Proxmox version, hostname, DNS override, VPN subnet, Cloudflare
     token, users, backups) are listed in `docs/headscale-setup.md`.
   - `docs/vm-setup.md` still describes hosted Tailscale and needs rewriting for this plan.
1. Start from `deploy/compose.yaml` + `deploy/.env.example`. Set `LONES_VDL_HOST_ARCHIVE` to the
   CIFS mount, and `PUID`/`PGID` to the share owner.
2. Reuse `deploy/vm/fix-vm-mount-boot.sh` (CIFS mount retries at boot) and `host-status.sh`
   (status report). They come from v1; review them.
3. Promote the same Git revision to the VM. To bring the current library over, copy
   `data/archive` to the share and use `lones-vdl state export` / `import` (see README "Move a
   library to another install"; verified between two containers). Add the alternate account's cookies on the Health
   page. Verify: an age-gated download; Range playback from the share; verify/rescan on CIFS.
4. **HTTPS for PWA install:** service workers and "install app" need a secure context. Plain
   `http://<vm-ip>:8080` works but cannot be installed. `tailscale serve` or a reverse proxy is
   the likely route. Ask before choosing.
5. Extend the VM runbook in `README.md`: first-run password, accounts and cookies, updates,
   backups of `<DATA_DIR>`.

## Phase 6 — Twitch

Source of the numbers: `docs/twitch-download-policy-original.md` (git-ignored, user-provided; its
values are proposed defaults, not Twitch thresholds). Twitch gets its own policy entry, caps,
pause, card, and Settings section; nothing is shared with YouTube.

**Differs from the YouTube policy** (so do not copy it blindly):

- **No daily count cap** by default. Limits come from concurrency, pacing, and rate-limit feedback.
- **No account ladder.** No automatic anonymous -> alternate -> personal escalation. Authenticate
  only when the user configured it for that content. 403 stops the job (`access_denied`, no
  automatic retry, no account fallback); 401 allows one token refresh, then `authentication_required`.
  Never rotate accounts, VPNs, or IPs.
- **Circuit breaker**: 3 consecutive rate-limit or access-denial incidents across distinct jobs
  within 15 minutes pause new Twitch jobs for 30 minutes (longer if the server says so). A 403'd
  job is not resumed when the breaker expires.

**Defaults to implement** (all editable except where noted):

| Setting | Default |
|---|---|
| Active Twitch downloads (VODs and clips together) | 1 |
| Concurrent fragments per job | 1 (fixed) |
| Gap between finished jobs | 20 s (between jobs, never per segment) |
| Metadata pacing | at most 1 request/s; cache same item 10 min |
| Channel status poll | at least 60 s; stable VOD list refresh 30 min |
| Transient retries | 3, backoff 5/15/45 s with jitter; honour server delays |
| 429 | pause the bucket; use `Retry-After`/`Ratelimit-Reset`, else 60 s then bounded backoff |
| 404 / deleted / expired | `unavailable`, no retries |

**New-VOD publish delay (decided 2026-10-23).** A VOD detected on a channel is not queued at
once. It becomes ready when the channel is offline, the VOD has been known for N minutes
(default 30, editable), and its duration was unchanged between two checks. Open: whether a live
stream's VOD id is visible while live.

**Authentication (decided 2026-10-23).** Optional cookies for one Twitch account, used only for
content the user marks as needing it; never an automatic fallback. Anonymous covers public
VODs and clips.

**Other rules from the policy file:** dedupe by video/clip id plus format; expiration-aware priority
uses the real expiry timestamp and never overrides cooldowns or permission failures; resume partial
downloads and validate before marking complete; per-job log of content type/id, attempts, status
code, cooldown-until, sanitized error; states `rate_limited`, `authentication_required`,
`access_denied`, `unavailable`, `retry_wait` visible in the UI; never log cookies, tokens, or
signed URLs. Verify whether Twitch goes through yt-dlp (expected), Streamlink, or the Helix API
before naming options. Tests: 429 timing, 403 stops, 401 refresh once, 5xx retries, shared
concurrency, duplicate jobs, resume.

## Backlog (agreed or noticed, not scheduled)

- Per-download "compatible" H.264 option (remux/derivative, never touching the original).
- Platform filter in the library and search. The API has no `platform` query param yet; add it
  with Twitch at the latest.
- Treat several consecutive failures of any kind (bot check, 403, unknown) as a suspected rate
  limit and pause, without switching accounts. Today only explicit 429 text pauses the queue.
- Fetch subtitles for many videos at once (today: per video, from the Watch page).
- Optional "approve for this channel" for the personal account (today: per job).
- `npm audit`: 5 low-severity warnings from an old `@sveltejs/kit`/`cookie` nested inside
  `bits-ui`. That code is server-side only and unused by the SPA. Recheck when `bits-ui` updates.
- Autoplay on arrival at the Watch page is untested in a real browser (headless blocks it).
- Video.js 10 is new (10.0.1, pinned). Consider upgrading after it matures; only
  `player.svelte` uses it.
- **Chapters and key moments.** Import `chapters` from `metadata.json`; show a clickable list on
  the Watch page and markers on the timeline. Also "most replayed" sections when yt-dlp provides
  them. Optional per video; videos without chapters must work as they do now.

## Findings that shaped the design

**Phase 0 (2026-10-22).** v1 image (yt-dlp 2026.10.21, Deno 2.9.7, yt-dlp-ejs 0.8.0, no PO-token
provider) against Windows yt-dlp, same home IP:

- Without cookies everything failed on both OSes ("Sign in to confirm you're not a bot"). Not a
  Linux/Docker problem.
- With valid cookies Docker worked fully, including an age-restricted 1080p AV1 download. PO
  tokens were not needed.
- Likely v1 causes: missing/expired/rotated cookies in the container, and/or a VM image built
  before Deno + yt-dlp-ejs were added (commit `7abc000`).
- Browser exporters produce full-browser jars (banking, shopping, AI sites). Import keeps only
  allowed domains. `youtube.com` alone is sufficient; do not keep `google.com` cookies.
- v1's filter treated `#HttpOnly_` rows as comments and dropped YouTube's login cookies. Some
  exporters write Chrome/WebKit timestamps (µs since 1601); import normalizes expiry.
- Deno + yt-dlp-ejs are essential. The bgutil PO-token sidecar is optional (opt-in profile;
  enable if 403s/bot checks return with cookies).

**Anonymous experiment (2026-10-23).** Same yt-dlp version and IP, no cookies, 3 requests: a
public HD video resolved (up to 2160p) and downloaded with no 403s. This contradicts Phase 0, so
bot checks are intermittent, not constant. Hence anonymous first, with escalation as the
fallback. Not tested: age-restricted videos, volume over days, the bgutil sidecar.

**First real rate limit (2026-10-23).** HTTP 429 on the *subtitle* request of an otherwise
working download. Subtitles are therefore no longer fetched with a video (see `AGENTS.md`).
