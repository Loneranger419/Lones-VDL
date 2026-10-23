"""Environment diagnostics: everything needed for a download to succeed, checked in one place."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from lones_vdl import __version__, cookie_jar
from lones_vdl.config import Settings
from lones_vdl.platforms import UrlKind, parse_url
from lones_vdl.schemas import CheckOut, DoctorReport
from lones_vdl.ytdlp import YtdlpError, YtdlpManager
from lones_vdl.ytdlp.errors import error_lines

OK, WARN, FAIL = "ok", "warn", "fail"
COOKIE_EXPIRY_WARN_DAYS = 14


@dataclass
class Doctor:
    settings: Settings
    ytdlp: YtdlpManager

    def run(self, *, test_url: str | None = None) -> DoctorReport:
        checks = [
            CheckOut(
                name="app",
                status=OK,
                detail=f"Lones-VDL {__version__}, Python {sys.version.split()[0]}",
            ),
            self._ytdlp(),
            self._tool("ffmpeg", ["-version"], required=True),
            self._tool("ffprobe", ["-version"], required=True),
            self._tool(
                "deno",
                ["--version"],
                required=True,
                why="needed to solve YouTube's JavaScript challenges",
            ),
            self._cookies(),
            self._writable("archive", self.settings.archive_root),
            self._writable("data", self.settings.data_dir),
        ]
        if test_url:
            checks.append(self._test_url(test_url))
        return DoctorReport(ok=all(c.status != FAIL for c in checks), checks=checks)

    def _ytdlp(self) -> CheckOut:
        command = self.ytdlp.command()
        if command is None:
            hint = (
                "the server installs it on start, or run `lones-vdl ytdlp update`"
                if self.ytdlp.managed
                else f"{self.settings.ytdlp_executable} not found"
            )
            return CheckOut(name="yt-dlp", status=FAIL, detail=f"not installed; {hint}")
        version = self.ytdlp.version(refresh=True)
        if version is None:
            return CheckOut(name="yt-dlp", status=FAIL, detail=f"{command[0]} does not run")
        source = "managed" if self.ytdlp.managed else "external"
        ejs = self._has_ejs(command)
        ejs_text = {True: "present", False: "MISSING", None: "unknown"}[ejs]
        detail = f"{version} ({source}); yt-dlp-ejs {ejs_text}"
        return CheckOut(name="yt-dlp", status=OK if ejs is not False else WARN, detail=detail)

    def _has_ejs(self, command: list[str]) -> bool | None:
        """yt-dlp-ejs ships with yt-dlp[default]. Only checkable for the managed venv."""
        if not self.ytdlp.managed:
            return None
        python = Path(command[0]).with_name("python.exe" if sys.platform == "win32" else "python")
        result = subprocess.run(
            [str(python), "-c", "import yt_dlp_ejs"], capture_output=True, check=False
        )
        return result.returncode == 0

    def _tool(self, name: str, args: list[str], *, required: bool, why: str = "") -> CheckOut:
        path = shutil.which(name)
        if path is None:
            detail = "not found on PATH" + (f" ({why})" if why else "")
            return CheckOut(name=name, status=FAIL if required else WARN, detail=detail)
        try:
            out = subprocess.run(
                [path, *args], capture_output=True, text=True, timeout=30, check=False
            ).stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CheckOut(name=name, status=FAIL, detail=f"does not run: {exc}")
        first = out.strip().splitlines()[0] if out.strip() else path
        return CheckOut(name=name, status=OK, detail=first[:200])

    def _cookies(self) -> CheckOut:
        path = self.settings.cookies_file
        if not path.is_file():
            return CheckOut(
                name="cookies",
                status=FAIL,
                detail="no cookies imported; YouTube currently refuses signed-out downloads",
            )
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            return CheckOut(name="cookies", status=FAIL, detail=f"unreadable: {exc}")
        cookies, summary = cookie_jar.filter_cookies(text, ["youtube"], drop_expired=True)
        login = [c for c in cookies if c.name in cookie_jar.AUTH_COOKIES["youtube"]]
        if not login:
            return CheckOut(
                name="cookies", status=FAIL, detail="no YouTube login cookies (or all expired)"
            )
        expiring = [c.expires for c in login if c.expires]
        if not expiring:
            return CheckOut(name="cookies", status=OK, detail="login cookies present (session)")
        days = (min(expiring) - time.time()) / 86400
        detail = (
            f"{len(cookies)} YouTube cookies; login expires in {days:.0f} days. "
            "Expiry does not detect rotation; use a test URL to confirm they still work."
        )
        return CheckOut(
            name="cookies", status=WARN if days < COOKIE_EXPIRY_WARN_DAYS else OK, detail=detail
        )

    def _writable(self, name: str, path: Path) -> CheckOut:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / f".write-test-{uuid.uuid4().hex}"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            return CheckOut(name=name, status=FAIL, detail=f"{path} not writable: {exc}")
        free = shutil.disk_usage(path).free / 1024**3
        return CheckOut(
            name=name,
            status=WARN if free < 10 else OK,
            detail=f"{path} writable, {free:.0f} GiB free",
        )

    def _test_url(self, url: str) -> CheckOut:
        name = "test download"
        parsed = parse_url(url)
        if parsed is None or parsed.kind != UrlKind.VIDEO:
            return CheckOut(name=name, status=FAIL, detail="not a YouTube video URL")
        url = parsed.url
        try:
            with self.ytdlp.using() as runner, tempfile.TemporaryDirectory() as tmp:
                info, _ = runner.resolve(url, quality="best", workdir=Path(tmp))
        except YtdlpError as exc:
            lines = error_lines(exc.detail, limit=3)
            detail = exc.message + (f" [{' | '.join(lines)}]" if lines else "")
            return CheckOut(name=name, status=FAIL, detail=detail[:1000])
        title = info.get("title") or info.get("id")
        fmt = info.get("format_id") or "?"
        return CheckOut(name=name, status=OK, detail=f"resolved '{title}' (format {fmt})")
