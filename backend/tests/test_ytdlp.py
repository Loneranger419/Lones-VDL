from __future__ import annotations

import pytest

from lones_vdl.config import Settings
from lones_vdl.services.downloads import ProgressTracker
from lones_vdl.ytdlp import ErrorKind, YtdlpManager
from lones_vdl.ytdlp.errors import classify
from lones_vdl.ytdlp.runner import format_selector, parse_progress

ROTATED = (
    "WARNING: [youtube] The provided YouTube account cookies are no longer valid. They have "
    "likely been rotated in the browser as a security measure.\n"
    "ERROR: [youtube] jNQXAC9IVRw: Sign in to confirm you’re not a bot."
)


@pytest.mark.parametrize(
    ("output", "has_cookies", "kind"),
    [
        (
            "ERROR: [youtube] x: Sign in to confirm you're not a bot.",
            False,
            ErrorKind.COOKIES_MISSING,
        ),
        ("ERROR: [youtube] x: Sign in to confirm you're not a bot.", True, ErrorKind.AUTH_REQUIRED),
        (ROTATED, True, ErrorKind.COOKIES_INVALID),
        ("ERROR: [youtube] x: Sign in to confirm your age.", True, ErrorKind.AUTH_REQUIRED),
        ("ERROR: [youtube] x: Video unavailable", False, ErrorKind.UNAVAILABLE),
        (
            "ERROR: [youtube] x: Private video. Sign in if you've been granted access",
            True,
            ErrorKind.UNAVAILABLE,
        ),
        (
            "ERROR: unable to download video data: HTTP Error 403: Forbidden",
            True,
            ErrorKind.FORBIDDEN,
        ),
        ("ERROR: HTTP Error 429: Too Many Requests", True, ErrorKind.RATE_LIMITED),
        (
            "ERROR: [youtube] x: Requested format is not available.",
            True,
            ErrorKind.FORMAT_UNAVAILABLE,
        ),
        ("ERROR: <urlopen error timed out>", True, ErrorKind.NETWORK),
        ("ERROR: something new and strange", True, ErrorKind.UNKNOWN),
        # WARNING lines must not drive classification when an ERROR exists
        (
            "WARNING: Video unavailable in one client\nERROR: HTTP Error 429",
            True,
            ErrorKind.RATE_LIMITED,
        ),
    ],
)
def test_classify(output, has_cookies, kind):
    assert classify(output, has_cookies=has_cookies) == kind


def test_format_selector():
    assert format_selector("best") == "bv*+ba/b"
    assert "height<=720" in format_selector("720")
    assert format_selector("audio") == "ba/b"
    with pytest.raises(ValueError):
        format_selector("8k")


def test_parse_progress():
    p = parse_progress("[lvdl] downloading|1500|3000|NA|1024.5|7|247")
    assert p is not None
    assert (p.downloaded_bytes, p.total_bytes, p.speed, p.eta, p.format_id) == (
        1500,
        3000,
        1024.5,
        7,
        "247",
    )
    estimate = parse_progress("[lvdl] downloading|10|NA|2000.0|NA|NA|NA")
    assert estimate is not None and estimate.total_bytes == 2000 and estimate.format_id is None
    assert parse_progress("[download] 50% of 10MiB") is None
    assert parse_progress("[lvdl] garbage") is None


def test_progress_tracker_combines_video_and_audio():
    seen = []
    tracker = ProgressTracker(1, expected_total=4000, report=seen.append)
    tracker.feed("[lvdl] downloading|3000|3000|NA|1|0|247")
    tracker.feed("[lvdl] downloading|500|1000|NA|1|0|251")
    tracker.feed('[Merger] Merging formats into "media.webm"')
    assert [round(s.progress, 3) for s in seen[:2]] == [0.75, 0.875]
    assert seen[-1].stage == "processing"


def test_manager_paths(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    manager = YtdlpManager(settings)
    assert manager.managed and not manager.installed and manager.command() is None
    external = YtdlpManager(Settings(_env_file=None, data_dir=tmp_path, ytdlp_executable="yt"))
    assert not external.managed and external.command() == ["yt"]


def test_manager_update_waits_for_running_jobs(tmp_path, monkeypatch):
    import threading
    import time

    settings = Settings(_env_file=None, data_dir=tmp_path)
    manager = YtdlpManager(settings, command=None)
    calls: list[str] = []
    monkeypatch.setattr(manager, "_uv", lambda cmd: calls.append(cmd[1]))
    monkeypatch.setattr(manager, "version", lambda refresh=False: "1.0")
    monkeypatch.setattr(manager, "runner", lambda: object())

    in_use = threading.Event()
    release = threading.Event()

    def job():
        with manager.using():
            in_use.set()
            release.wait(5)

    worker = threading.Thread(target=job)
    worker.start()
    in_use.wait(5)
    updater = threading.Thread(target=manager.install_or_update)
    updater.start()
    time.sleep(0.2)
    assert calls == []  # blocked behind the running job
    release.set()
    updater.join(5)
    worker.join(5)
    assert calls == ["venv", "pip"]
