"""Own the yt-dlp installation: a venv under data_dir/ytdlp, updated in place with uv.

Keeping yt-dlp out of the image means YouTube breakages are fixed by an update, not a rebuild.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from lones_vdl.config import Settings
from lones_vdl.ytdlp.errors import ErrorKind, YtdlpError
from lones_vdl.ytdlp.runner import YtdlpRunner

logger = logging.getLogger(__name__)

PACKAGES = ("yt-dlp[default]",)


@dataclass(frozen=True)
class UpdateResult:
    before: str | None
    after: str


class YtdlpManager:
    def __init__(self, settings: Settings, *, command: list[str] | None = None) -> None:
        self.settings = settings
        self._override = command or (
            [settings.ytdlp_executable] if settings.ytdlp_executable else None
        )
        self._cond = threading.Condition()
        self._active = 0
        self._updating = False
        self._version: str | None = None

    @property
    def managed(self) -> bool:
        return self._override is None

    @property
    def venv_dir(self) -> Path:
        return self.settings.ytdlp_dir

    def _venv_bin(self, name: str) -> Path:
        if sys.platform == "win32":
            return self.venv_dir / "Scripts" / f"{name}.exe"
        return self.venv_dir / "bin" / name

    def command(self) -> list[str] | None:
        if self._override is not None:
            return list(self._override)
        exe = self._venv_bin("yt-dlp")
        return [str(exe)] if exe.is_file() else None

    @property
    def installed(self) -> bool:
        return self.command() is not None

    def runner(self) -> YtdlpRunner:
        command = self.command()
        if command is None:
            raise YtdlpError(ErrorKind.YTDLP_MISSING)
        return YtdlpRunner(
            command,
            cookies_file=self.settings.cookies_file,
            tmp_dir=self.settings.data_dir / "tmp",
        )

    def version(self, *, refresh: bool = False) -> str | None:
        if self._version is None or refresh:
            try:
                self._version = self.runner().version()
            except YtdlpError:
                self._version = None
        return self._version

    @contextlib.contextmanager
    def using(self) -> Iterator[YtdlpRunner]:
        """Hold while running yt-dlp; updates wait for all holders to finish."""
        with self._cond:
            while self._updating:
                self._cond.wait()
            self._active += 1
        try:
            yield self.runner()
        finally:
            with self._cond:
                self._active -= 1
                self._cond.notify_all()

    def install_or_update(self, channel: str | None = None) -> UpdateResult:
        """Create the venv if needed and install/upgrade yt-dlp. Blocks until jobs drain.

        Switching nightly → stable takes effect at the next stable release (no downgrade)."""
        channel = channel or self.settings.ytdlp_channel
        if not self.managed:
            raise RuntimeError("yt-dlp is externally managed (LONES_VDL_YTDLP_EXECUTABLE set)")
        with self._cond:
            while self._updating:
                self._cond.wait()
            self._updating = True
            while self._active:
                self._cond.wait()
        try:
            before = self.version(refresh=True)
            uv = self.settings.uv_executable or os.environ.get("UV") or "uv"
            python = self._venv_bin("python")
            if not python.is_file():
                self._uv([uv, "venv", "--python", sys.executable, str(self.venv_dir)])
            cmd = [uv, "pip", "install", "--python", str(python), "--upgrade", *PACKAGES]
            if channel == "nightly":
                cmd[3:3] = ["--prerelease", "allow"]
            self._uv(cmd)
            after = self.version(refresh=True)
            if after is None:
                raise YtdlpError(ErrorKind.YTDLP_MISSING, "installed but --version failed")
            if before != after:
                logger.info("yt-dlp %s -> %s", before or "(none)", after)
            return UpdateResult(before=before, after=after)
        finally:
            with self._cond:
                self._updating = False
                self._cond.notify_all()

    def _uv(self, cmd: list[str]) -> None:
        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600, check=False
            )
        except FileNotFoundError as exc:
            raise YtdlpError(ErrorKind.YTDLP_MISSING, f"uv not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise YtdlpError(ErrorKind.YTDLP_MISSING, "uv timed out") from exc
        if completed.returncode != 0:
            raise YtdlpError(ErrorKind.YTDLP_MISSING, completed.stderr[-2000:])
