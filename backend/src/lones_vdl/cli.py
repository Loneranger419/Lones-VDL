"""Command line entry point: ``lones-vdl <command>``."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from lones_vdl import __version__


def _drop_root() -> None:
    """`docker compose exec` runs as root; act as the app user so files we create (cookies,
    yt-dlp venv, DB) stay readable by the server."""
    if os.name != "posix" or os.geteuid() != 0 or "PUID" not in os.environ:
        return
    os.setgroups([])
    os.setgid(int(os.environ.get("PGID", os.environ["PUID"])))
    os.setuid(int(os.environ["PUID"]))


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from lones_vdl.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "lones_vdl.main:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_level=settings.log_level,
        reload=args.reload,
    )
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from lones_vdl.config import get_settings
    from lones_vdl.services.doctor import Doctor
    from lones_vdl.ytdlp import YtdlpManager

    settings = get_settings()
    report = Doctor(settings, YtdlpManager(settings)).run(test_url=args.url)
    marks = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    for check in report.checks:
        print(f"[{marks[check.status]}] {check.name}: {check.detail}")
    return 0 if report.ok else 1


def _set_password(args: argparse.Namespace) -> int:
    from lones_vdl.config import get_settings
    from lones_vdl.db import create_db_engine, make_sessionmaker, upgrade
    from lones_vdl.services import auth

    password = getpass.getpass("New admin password: ")
    if password != getpass.getpass("Repeat: "):
        print("passwords do not match", file=sys.stderr)
        return 1
    settings = get_settings()
    engine = create_db_engine(settings.database_path)
    try:
        upgrade(engine)
        with make_sessionmaker(engine).begin() as db:
            auth.set_password(db, password)
    except auth.PasswordPolicyError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print("password set; all sessions signed out")
    return 0


def _cookies_import(args: argparse.Namespace) -> int:
    from lones_vdl.config import get_settings
    from lones_vdl.services.cookies import CookieImportError, import_cookies

    settings = get_settings()
    from_stdin = args.file == "-"
    try:
        if from_stdin:
            text = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
        else:
            text = Path(args.file).read_text(encoding="utf-8-sig", errors="replace")
        summary = import_cookies(settings, text)
    except (OSError, CookieImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    found = summary.auth_cookies.get("youtube", {})
    print(f"imported {summary.kept} YouTube cookies to {settings.cookies_file}")
    print("login cookies: " + ", ".join(f"{n} (expires {d})" for n, d in found.items()))
    if args.delete_source and not from_stdin:
        Path(args.file).unlink()
        print(f"deleted {args.file}")
    return 0


def _ytdlp_update(args: argparse.Namespace) -> int:
    from lones_vdl.config import get_settings
    from lones_vdl.ytdlp import YtdlpError, YtdlpManager

    manager = YtdlpManager(get_settings())
    if not manager.managed:
        print("yt-dlp is externally managed (LONES_VDL_YTDLP_EXECUTABLE)", file=sys.stderr)
        return 1
    try:
        result = manager.install_or_update()
    except YtdlpError as exc:
        print(f"error: {exc.detail or exc.message}", file=sys.stderr)
        return 1
    print(f"yt-dlp {result.before or '(not installed)'} -> {result.after}")
    return 0


def openapi_json() -> str:
    """The API schema the frontend client is generated from (deterministic output)."""
    import json

    from lones_vdl.config import Settings
    from lones_vdl.main import create_app

    app = create_app(Settings(_env_file=None, frontend_dist=Path("/nonexistent")))
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def _openapi(args: argparse.Namespace) -> int:
    text = openapi_json()
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


def _make_migration(args: argparse.Namespace) -> int:
    from lones_vdl.db.migrate import make_migration

    make_migration(args.message)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _drop_root()

    # `cookies filter` keeps the standalone tool's own argument parser.
    if argv[:2] == ["cookies", "filter"]:
        from lones_vdl import cookie_jar

        return cookie_jar.main(argv[2:], prog="lones-vdl cookies filter")

    parser = argparse.ArgumentParser(prog="lones-vdl")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the web server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    serve.set_defaults(func=_serve)

    doctor = commands.add_parser("doctor", help="check the environment")
    doctor.add_argument("--url", help="also resolve this video URL (no download)")
    doctor.set_defaults(func=_doctor)

    password = commands.add_parser("set-password", help="set the admin password")
    password.set_defaults(func=_set_password)

    cookies = commands.add_parser("cookies", help="manage YouTube cookies")
    cookie_commands = cookies.add_subparsers(dest="cookies_command", required=True)
    cookie_import = cookie_commands.add_parser(
        "import", help="filter a browser export and install it for downloads"
    )
    cookie_import.add_argument("file", help="cookies.txt exported from a browser, or - for stdin")
    cookie_import.add_argument(
        "--delete-source", action="store_true", help="delete the export after importing"
    )
    cookie_import.set_defaults(func=_cookies_import)
    cookie_commands.add_parser(
        "filter", help="filter a cookies.txt file in place or to another file", add_help=False
    )

    ytdlp = commands.add_parser("ytdlp", help="manage the yt-dlp installation")
    ytdlp_commands = ytdlp.add_subparsers(dest="ytdlp_command", required=True)
    ytdlp_commands.add_parser("update", help="install or upgrade yt-dlp").set_defaults(
        func=_ytdlp_update
    )

    openapi = commands.add_parser("openapi", help="print the API schema (for the frontend)")
    openapi.add_argument("-o", "--output", help="write to this file instead of stdout")
    openapi.set_defaults(func=_openapi)

    db = commands.add_parser("db", help="database maintenance (development)")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    migration = db_commands.add_parser("make-migration", help="autogenerate a migration")
    migration.add_argument("message")
    migration.set_defaults(func=_make_migration)

    args = parser.parse_args(argv)
    return args.func(args)
