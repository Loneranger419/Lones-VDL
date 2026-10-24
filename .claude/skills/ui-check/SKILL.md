---
name: ui-check
description: Check Lones-VDL pages in a real browser on Windows by driving headless Edge over the DevTools protocol (no Playwright here). Use after frontend changes to verify pages at desktop/phone widths, playback, and flows against the Docker dev container.
---

# UI check with headless Edge

Prerequisite: the Docker dev container is running at http://localhost:8080
(`docker compose -f deploy/compose.yaml -f deploy/compose.dev.yaml up -d --build`). Dev password:
`docker-test-pass`. It holds archived test videos and real cookies, so do not run destructive
actions in it; avoid requests that make YouTube calls.

No Playwright. Drive Edge with Python `websocket-client` (installed system-wide):

1. Start Edge: `msedge --headless=new --remote-debugging-port=9333 --user-data-dir=<tmp dir>`
   (use a scratchpad directory for `<tmp dir>`).
2. Log in without the UI: `POST /api/auth/login` with header `x-lones-vdl: 1`, then set the
   session cookie in the browser with `Network.setCookie`.
3. Open a **fresh tab per page** via `PUT http://localhost:9333/json/new?<url>`. Reusing one tab
   across navigations stalled.
4. Connect to the tab's `webSocketDebuggerUrl` with `suppress_origin=True`.
5. Use `Emulation.setDeviceMetricsOverride` for phone widths; `Page.captureScreenshot` to look
   at the result; `Runtime.evaluate` to read the DOM or click.
6. In Git Bash, set `MSYS_NO_PATHCONV=1` so `/library`-style arguments are not rewritten.

Headless Edge blocks autoplay, so autoplay on the Watch page cannot be checked this way.
Stop Edge when done and delete the temp profile.
