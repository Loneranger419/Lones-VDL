"""Stand-in for the yt-dlp CLI, run as a real subprocess by the tests.

Behaviour is chosen by the video id prefix:
    bot*      sign-in / bot check            rot*      cookies rotated + bot check
    gone*     video unavailable              flaky*    HTTP 429 on the first resolve only
    limited*  HTTP 429 on every resolve      slow*     slow download (for cancel tests)
    subfail*  media ok, subtitle error       dlfmt*    resolves, then the download fails
    nosubs*   a subtitle fetch finds no captions (media downloads never write subtitles unless
              asked: they come only from `--write-subs`)
    login*    bot check unless cookies       private*  private video unless cookies
    member*   members-only unless the cookies hold MEMBERSHIP
    anything else: success
--flat-playlist listings come from $FAKE_YTDLP_STATE/listings.json:
    {"videos": [entries], "streams": [...], "playlist": [...]}; a missing tab key means the
    channel has no such tab. Entries are video ids or {"id", "live_status"} objects.
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


def chapters_ready() -> bool:
    """Tests create this file to make chapters appear on videos that had none."""
    state = os.environ.get("FAKE_YTDLP_STATE")
    return bool(state) and (Path(state) / "chapters_ready").exists()


def info_for(video_id: str) -> dict:
    # Ids containing "short" are portrait and brief, like a YouTube short.
    short = "short" in video_id
    return {
        "id": video_id,
        "title": f"Title {video_id}",
        "description": "A fake video.",
        "channel": "Fake Channel",
        "channel_id": "UC" + "x" * 22,
        "channel_url": "https://www.youtube.com/channel/UC" + "x" * 22,
        "uploader_id": "@fakechannel",
        # Ids containing "new" were published today; the others long ago.
        "upload_date": time.strftime("%Y%m%d", time.gmtime()) if "new" in video_id else "20240102",
        "duration": 30 if short else 63,
        "width": 720 if short else 1280,
        "height": 1280 if short else 720,
        "view_count": 1234,
        "like_count": 56,
        # Ids containing "asmr" get that tag too; the duplicate differs only in case.
        "tags": ["Sleep", "ASMR", "asmr"] if "asmr" in video_id else ["Sleep", "Fake"],
        **(
            {
                "chapters": [
                    {"start_time": 0, "end_time": 20, "title": "Intro & <setup>"},
                    {"start_time": 20, "end_time": 63, "title": "Main part"},
                ],
                "heatmap": [
                    {"start_time": 0.0, "end_time": 31.5, "value": 0.4},
                    {"start_time": 31.5, "end_time": 63.0, "value": 1.0},
                ],
            }
            if "chap" in video_id or ("late" in video_id and chapters_ready())
            else {}
        ),
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
    record("calls", f"{vid} {'auth' if cookies else 'anon'}")
    if cookies:
        record("cookies_seen", cookies)
        if not Path(cookies).is_file():
            fail("ERROR: cookie file passed but missing")
    if vid.startswith("login") and not cookies:
        fail(f"ERROR: [youtube] {vid}: Sign in to confirm you’re not a bot.")
    if vid.startswith("member") and not (cookies and "MEMBERSHIP" in Path(cookies).read_text()):
        fail(
            f"ERROR: [youtube] {vid}: Join this channel to get access to members-only content "
            "like this video, and other exclusive perks."
        )
    if vid.startswith("private") and not cookies:
        fail(f"ERROR: [youtube] {vid}: Private video. Sign in if you've been granted access")
    if vid.startswith("limited"):
        fail("ERROR: [youtube] limited: HTTP Error 429: Too Many Requests")
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
    if vid.startswith("dlfmt"):
        fail("ERROR: [youtube] Requested format is not available.")
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
    if "--write-subs" in args:
        (workdir / "subtitles").mkdir(exist_ok=True)
        (workdir / "subtitles" / "subs.en.vtt").write_text("WEBVTT\n")
        if vid.startswith("subfail"):
            fail("ERROR: Unable to download video subtitles for 'de': HTTP Error 429")


def subtitles(args: list[str]) -> None:
    vid = video_id_from(args[-1])
    cookies = arg_after(args, "--cookies")
    record("subtitle_calls", f"{vid} {'auth' if cookies else 'anon'}")
    workdir = Path(arg_after(args, "--paths"))
    if vid.startswith("limited"):
        fail(
            "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
        )
    if vid.startswith("nosubs"):
        return
    (workdir / "subtitles").mkdir(parents=True, exist_ok=True)
    (workdir / "subtitles" / "subs.en.vtt").write_text("WEBVTT\n")


CHANNEL_ID = "UC" + "x" * 22
DEFAULT_LISTINGS = {"videos": ["okokokokok1", "okokokokok2"], "playlist": ["okokokokok3"]}


def listing(args: list[str]) -> None:
    url = args[-1]
    record("listings", f"{url} {'auth' if arg_after(args, '--cookies') else 'anon'}")
    state = os.environ.get("FAKE_YTDLP_STATE")
    path = Path(state) / "listings.json" if state else None
    listings = (
        json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else DEFAULT_LISTINGS
    )
    tab = "playlist" if "list=" in url else url.rstrip("/").rsplit("/", 1)[-1]
    if "@botchannel" in url:
        fail("ERROR: [youtube:tab] Sign in to confirm you’re not a bot.")
    if tab not in listings:
        fail(f"ERROR: [youtube:tab] @fakechannel: This channel does not have a {tab} tab")
    entries = []
    for item in listings[tab]:
        item = {"id": item} if isinstance(item, str) else item
        entries.append(
            {
                "_type": "url",
                "ie_key": "Youtube",
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "title": f"Title {item['id']}",
                **item,
            }
        )
    end = arg_after(args, "--playlist-end")
    if end:
        entries = entries[: int(end)]
    print(
        json.dumps(
            {
                "_type": "playlist",
                "id": "PLfake" if tab == "playlist" else CHANNEL_ID,
                "title": "Fake Playlist" if tab == "playlist" else f"Fake Channel - {tab}",
                "channel": "Fake Channel",
                "channel_id": CHANNEL_ID,
                "uploader_id": "@fakechannel",
                "channel_url": f"https://www.youtube.com/channel/{CHANNEL_ID}",
                "description": "About the fake channel.",
                "thumbnails": [
                    {"id": "avatar_uncropped", "url": "https://yt3.example.com/avatar"},
                    {"id": "banner_uncropped", "url": "https://yt3.example.com/banner"},
                ],
                "entries": entries,
            }
        )
    )


def main() -> None:
    args = sys.argv[1:]
    if "--version" in args:
        print(VERSION)
    elif "--flat-playlist" in args:
        listing(args)
    elif "--skip-download" in args:
        subtitles(args)
    elif "--dump-single-json" in args:
        resolve(args)
    elif "--load-info-json" in args:
        download(args)
    else:
        fail("ERROR: fake yt-dlp: unsupported invocation")


if __name__ == "__main__":
    main()
