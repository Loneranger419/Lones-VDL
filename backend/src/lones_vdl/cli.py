"""Command line entry point: ``lones-vdl <command>``."""

from __future__ import annotations

import argparse
import sys

from lones_vdl import __version__


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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="lones-vdl")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the web server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    serve.set_defaults(func=_serve)

    commands.add_parser(
        "cookies",
        help="filter a browser cookie export (see: lones-vdl cookies --help)",
        add_help=False,
    )

    # Delegate `cookies ...` wholesale so the cookie tool keeps its own argument parser.
    if argv and argv[0] == "cookies":
        from lones_vdl import cookie_jar

        return cookie_jar.main(argv[1:], prog="lones-vdl cookies")

    args = parser.parse_args(argv)
    return args.func(args)
