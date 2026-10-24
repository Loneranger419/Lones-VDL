"""Run yt-dlp as a subprocess: build commands, stream output, parse progress, cancel.

Synchronous by design (called from worker threads): asyncio subprocesses are unavailable
under some Windows event loops, and a thread with a blocking pipe is simple and killable.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from lones_vdl.ytdlp.errors import ErrorKind, YtdlpError, classify, error_lines

PROGRESS_PREFIX = "[lvdl] "
PROGRESS_TEMPLATE = (
    PROGRESS_PREFIX
    + "|".join(
        f"%(progress.{field})s"
        for field in (
            "status",
            "downloaded_bytes",
            "total_bytes",
            "total_bytes_estimate",
            "speed",
            "eta",
        )
    )
    + "|%(info.format_id)s"
)

# Download policy: slow extraction, one fragment at a time, and few yt-dlp-internal retries
# (the app does its own, counted retries).
PACING_ARGS = [
    "--sleep-requests",
    "2",
    "--concurrent-fragments",
    "1",
    "--retries",
    "2",
    "--fragment-retries",
    "2",
    "--extractor-retries",
    "1",
]

# yt-dlp: "This channel does not have a streams tab".
_MISSING_TAB = "does not have a"

SUBTITLE_ARGS = [
    "--output",
    "subtitle:subtitles/subs.%(ext)s",
    "--write-subs",
    "--write-auto-subs",
    "--sub-langs",
    "en,en-orig,en-US,en-GB",
    "--convert-subs",
    "vtt",
]

# Containers tried in order when merging video+audio: browser-playable first, no re-encode.
MERGE_FORMATS = "webm/mp4/mkv"

QUALITIES = ("best", "2160", "1440", "1080", "720", "480", "360", "audio")


def format_selector(quality: str) -> str:
    if quality == "best":
        return "bv*+ba/b"
    if quality == "audio":
        return "ba/b"
    if quality.isdigit():
        h = int(quality)
        return f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
    raise ValueError(f"unknown quality: {quality}")


@dataclass(frozen=True)
class Progress:
    status: str
    downloaded_bytes: int | None
    total_bytes: int | None
    speed: float | None
    eta: int | None
    format_id: str | None


def _num(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None  # "NA" / "None"


def parse_progress(line: str) -> Progress | None:
    if not line.startswith(PROGRESS_PREFIX):
        return None
    parts = line[len(PROGRESS_PREFIX) :].strip().split("|")
    if len(parts) != 7:
        return None
    status, done, total, estimate, speed, eta, format_id = parts
    total_value = _num(total) or _num(estimate)
    done_value = _num(done)
    eta_value = _num(eta)
    return Progress(
        status=status,
        downloaded_bytes=int(done_value) if done_value is not None else None,
        total_bytes=int(total_value) if total_value else None,
        speed=_num(speed),
        eta=int(eta_value) if eta_value is not None else None,
        format_id=format_id if format_id not in {"NA", "None", ""} else None,
    )


class CancelToken:
    """Shared between the worker (cancel) and the runner (attach the live process)."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def attach(self, proc: subprocess.Popen[str] | None) -> None:
        with self._lock:
            self._proc = proc
        if proc is not None and self.cancelled:
            _kill_tree(proc)

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            proc = self._proc
        if proc is not None:
            _kill_tree(proc)


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    """Terminate yt-dlp and its children (ffmpeg)."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class RunResult:
    returncode: int
    output: str  # tail of combined output (progress lines excluded)


class YtdlpRunner:
    def __init__(
        self,
        command: list[str],
        *,
        cookies_file: Path | None = None,
        tmp_dir: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.cookies_file = cookies_file
        self.tmp_dir = tmp_dir
        self.env = env

    @property
    def has_cookies(self) -> bool:
        return self.cookies_file is not None and self.cookies_file.is_file()

    @contextlib.contextmanager
    def _cookie_args(self) -> Iterator[list[str]]:
        """Give each run a private copy: yt-dlp writes cookies back, and the copy must stay
        on local disk (tmp_dir under the data dir), never on the archive share."""
        if not self.has_cookies:
            yield []
            return
        assert self.cookies_file is not None
        if self.tmp_dir is not None:
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="cookies-", suffix=".txt", dir=self.tmp_dir)
        os.close(fd)
        path = Path(name)
        try:
            shutil.copyfile(self.cookies_file, path)
            os.chmod(path, 0o600)
            yield ["--cookies", str(path)]
        finally:
            path.unlink(missing_ok=True)

    def run(
        self,
        args: list[str],
        *,
        log: TextIO | None = None,
        on_line: Callable[[str], None] | None = None,
        cancel: CancelToken | None = None,
        stdout_file: Path | None = None,
    ) -> RunResult:
        """Run yt-dlp. With stdout_file, stdout goes to that file and only stderr is streamed."""
        tail: deque[str] = deque(maxlen=200)
        with self._cookie_args() as cookie_args:
            cmd = [
                *self.command,
                "--ignore-config",
                "--no-colors",
                *PACING_ARGS,
                *cookie_args,
                *args,
            ]
            popen_kwargs: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stderr": subprocess.STDOUT if stdout_file is None else subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
                "env": {**os.environ, **(self.env or {}), "PYTHONIOENCODING": "utf-8"},
            }
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True

            out_handle = open(stdout_file, "w", encoding="utf-8") if stdout_file else None
            try:
                popen_kwargs["stdout"] = out_handle or subprocess.PIPE
                try:
                    proc = subprocess.Popen(cmd, **popen_kwargs)
                except FileNotFoundError as exc:
                    raise YtdlpError(ErrorKind.YTDLP_MISSING, str(exc)) from exc
                if cancel is not None:
                    cancel.attach(proc)
                try:
                    stream = proc.stdout if stdout_file is None else proc.stderr
                    assert stream is not None
                    for raw in stream:
                        line = raw.rstrip("\r\n")
                        if on_line is not None:
                            on_line(line)
                        if line.startswith(PROGRESS_PREFIX):
                            continue
                        tail.append(line)
                        if log is not None:
                            log.write(line + "\n")
                    returncode = proc.wait()
                finally:
                    if cancel is not None:
                        cancel.attach(None)
                    if proc.poll() is None:
                        _kill_tree(proc)
                    for pipe in (proc.stdout, proc.stderr):
                        if pipe is not None and pipe is not out_handle:
                            pipe.close()
            finally:
                if out_handle is not None:
                    out_handle.close()
        if log is not None:
            log.flush()
        if cancel is not None and cancel.cancelled:
            raise Cancelled()
        return RunResult(returncode=returncode, output="\n".join(tail))

    def _check(self, result: RunResult) -> None:
        if result.returncode != 0:
            raise YtdlpError(classify(result.output, has_cookies=self.has_cookies), result.output)

    def version(self) -> str:
        try:
            completed = subprocess.run(
                [*self.command, "--version"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise YtdlpError(ErrorKind.YTDLP_MISSING, str(exc)) from exc
        if completed.returncode != 0:
            raise YtdlpError(ErrorKind.YTDLP_MISSING, completed.stderr)
        return completed.stdout.strip().splitlines()[-1]

    def resolve(
        self,
        url: str,
        *,
        quality: str,
        workdir: Path,
        log: TextIO | None = None,
        cancel: CancelToken | None = None,
        verbose: bool = True,
    ) -> tuple[dict[str, Any], Path]:
        """Extract metadata (with the chosen format) without downloading media."""
        workdir.mkdir(parents=True, exist_ok=True)
        info_path = workdir / "resolved.json"
        args = [
            *(["-v"] if verbose else []),
            "--no-playlist",
            "--dump-single-json",
            "--format",
            format_selector(quality),
            url,
        ]
        result = self.run(args, log=log, cancel=cancel, stdout_file=info_path)
        self._check(result)
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise YtdlpError(ErrorKind.UNKNOWN, f"unreadable metadata: {exc}") from exc
        if not isinstance(info, dict) or not info.get("id"):
            raise YtdlpError(ErrorKind.UNKNOWN, "metadata missing id")
        return info, info_path

    def list_entries(
        self,
        url: str,
        *,
        workdir: Path,
        limit: int | None = None,
        log: TextIO | None = None,
        cancel: CancelToken | None = None,
    ) -> dict[str, Any] | None:
        """Flat-list a playlist or channel tab (no per-video requests).

        Returns the playlist JSON (with ``entries``), or None if the tab does not exist.
        """
        workdir.mkdir(parents=True, exist_ok=True)
        out = workdir / f"listing-{uuid.uuid4().hex}.json"
        args = ["--flat-playlist", "--dump-single-json"]
        if limit:
            args += ["--playlist-end", str(limit)]
        try:
            result = self.run([*args, url], log=log, cancel=cancel, stdout_file=out)
            if result.returncode != 0:
                if _MISSING_TAB in result.output.lower():
                    return None
                self._check(result)
            data = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise YtdlpError(ErrorKind.UNKNOWN, f"unreadable listing: {exc}") from exc
        finally:
            out.unlink(missing_ok=True)
        if not isinstance(data, dict):
            raise YtdlpError(ErrorKind.UNKNOWN, "listing is not an object")
        return data

    def download(
        self,
        info_path: Path,
        *,
        quality: str,
        workdir: Path,
        log: TextIO | None = None,
        on_line: Callable[[str], None] | None = None,
        cancel: CancelToken | None = None,
        subtitles: bool = False,
    ) -> None:
        """Download media, thumbnail, and info JSON into workdir. Subtitles only on request:
        YouTube throttles that request separately, and it is not worth failing a video over."""
        args = [
            "-v",
            "--newline",
            "--no-mtime",
            "--load-info-json",
            str(info_path),
            "--paths",
            str(workdir),
            "--format",
            format_selector(quality),
            "--merge-output-format",
            MERGE_FORMATS,
            "--output",
            "media.%(ext)s",
            "--output",
            "thumbnail:thumbnail.%(ext)s",
            "--output",
            "infojson:info.%(ext)s",
            "--write-info-json",
            "--write-thumbnail",
            "--convert-thumbnails",
            "jpg",
            "--progress-template",
            f"download:{PROGRESS_TEMPLATE}",
        ]
        if subtitles:
            args += SUBTITLE_ARGS
        result = self.run(args, log=log, on_line=on_line, cancel=cancel)
        if result.returncode != 0:
            # Subtitle/thumbnail failures are non-fatal when the media made it.
            if any(workdir.glob("media.*")) and _only_sidecar_errors(result.output):
                return
            self._check(result)

    def fetch_subtitles(
        self,
        url: str,
        *,
        workdir: Path,
        log: TextIO | None = None,
        on_line: Callable[[str], None] | None = None,
        cancel: CancelToken | None = None,
    ) -> None:
        """Download only the subtitles of an already archived video into workdir/subtitles."""
        args = ["-v", "--newline", "--skip-download", "--paths", str(workdir), *SUBTITLE_ARGS, url]
        self._check(self.run(args, log=log, on_line=on_line, cancel=cancel))


def _only_sidecar_errors(output: str) -> bool:
    errors = error_lines(output)
    return bool(errors) and all("subtitle" in e.lower() or "thumbnail" in e.lower() for e in errors)
