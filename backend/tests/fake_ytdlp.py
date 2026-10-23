"""Stand-in for the yt-dlp CLI, run as a real subprocess by the tests.

Behaviour is chosen by the video id prefix:
    bot*     sign-in / bot check          rot*     cookies rotated + bot check
    gone*    video unavailable            flaky*   HTTP 429 on the first resolve only
    subfail* media ok, subtitle error     slow*    slow download (for cancel tests)
    anything else: success
State (call counts, cookie paths seen) goes to $FAKE_YTDLP_STATE.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERSION = "2099.01.01"


def arg_after(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args else None


def video_id_from(url: str) -> str:
    return parse_qs(urlparse(url).query).get("v", ["unknown"])[0]


def record(name: str, value: str) -> None:
    state = os.environ.get("FAKE_YTDLP_STATE")
    if state:
        with open(Path(state) / name, "a", encoding="utf-8") as fh:
            fh.write(value + "\n")


def count(name: str) -> int:
    state = os.environ.get("FAKE_YTDLP_STATE")
    if not state:
        return 0
    path = Path(state) / name
    return len(path.read_text().splitlines()) if path.exists() else 0


def fail(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr)
    sys.exit(1)


def info_for(video_id: str) -> dict:
    return {
        "id": video_id,
        "title": f"Title {video_id}",
        "description": "A fake video.",
        "channel": "Fake Channel",
        "channel_id": "UC" + "x" * 22,
        "channel_url": "https://www.youtube.com/channel/UC" + "x" * 22,
        "uploader_id": "@fakechannel",
        "upload_date": "20240102",
        "duration": 63,
        "width": 1280,
        "height": 720,
        "view_count": 1234,
        "like_count": 56,
        "format_id": "247+251",
        "ext": "webm",
        "requested_formats": [
            {"format_id": "247", "filesize": 3000},
            {"format_id": "251", "filesize": 1000},
        ],
    }


def resolve(args: list[str]) -> None:
    url = args[-1]
    vid = video_id_from(url)
    cookies = arg_after(args, "--cookies")
    if cookies:
        record("cookies_seen", cookies)
        if not Path(cookies).is_file():
            fail("ERROR: cookie file passed but missing")
    if vid.startswith("bot"):
        fail(f"ERROR: [youtube] {vid}: Sign in to confirm you’re not a bot.")
    if vid.startswith("rot"):
        fail(
            "WARNING: [youtube] The provided YouTube account cookies are no longer valid.",
            f"ERROR: [youtube] {vid}: Sign in to confirm you’re not a bot.",
        )
    if vid.startswith("gone"):
        fail(f"ERROR: [youtube] {vid}: Video unavailable")
    if vid.startswith("flaky"):
        record("flaky_calls", vid)
        if count("flaky_calls") == 1:
            fail("ERROR: [youtube] flaky: HTTP Error 429: Too Many Requests")
    print("[debug] fake resolve", file=sys.stderr)
    print(json.dumps(info_for(vid)))


def progress(done: int, total: int, fmt: str) -> None:
    print(f"[lvdl] downloading|{done}|{total}|NA|1000.0|1|{fmt}", flush=True)


def download(args: list[str]) -> None:
    info = json.loads(Path(arg_after(args, "--load-info-json")).read_text(encoding="utf-8"))
    workdir = Path(arg_after(args, "--paths"))
    vid = info["id"]
    if vid.startswith("slow"):
        for i in range(300):
            progress(i, 300, "247")
            time.sleep(0.1)
    for done in (0, 1500, 3000):
        progress(done, 3000, "247")
    for done in (0, 1000):
        progress(done, 1000, "251")
    print('[Merger] Merging formats into "media.webm"', flush=True)
    (workdir / "media.webm").write_bytes(b"\x1aE\xdf\xa3" + b"0" * 3996)
    (workdir / "media.f247.webm.part").write_bytes(b"leftover")
    (workdir / "info.info.json").write_text(json.dumps({**info, "downloaded": True}))
    (workdir / "thumbnail.jpg").write_bytes(b"\xff\xd8\xff")
    (workdir / "subtitles").mkdir(exist_ok=True)
    (workdir / "subtitles" / "subs.en.vtt").write_text("WEBVTT\n")
    if vid.startswith("subfail"):
        fail("ERROR: Unable to download video subtitles for 'de': HTTP Error 429")


def main() -> None:
    args = sys.argv[1:]
    if "--version" in args:
        print(VERSION)
    elif "--dump-single-json" in args:
        resolve(args)
    elif "--load-info-json" in args:
        download(args)
    else:
        fail("ERROR: fake yt-dlp: unsupported invocation")


if __name__ == "__main__":
    main()
