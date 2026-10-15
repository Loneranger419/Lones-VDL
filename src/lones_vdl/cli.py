"""Simple CLI helpers for local archive operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lones_vdl.config import get_settings
from lones_vdl.db import Database
from lones_vdl.download.service import ArchiveService
from lones_vdl.errors import DuplicateArchiveError, LonesVdlError
from lones_vdl.platform.ytdlp import YtdlpCliAdapter


def _build_service() -> ArchiveService:
    settings = get_settings()
    settings.archive_root = Path(settings.archive_root)
    settings.database_path = Path(settings.database_path)
    settings.archive_root.mkdir(parents=True, exist_ok=True)
    db = Database(settings.database_path)
    adapter = YtdlpCliAdapter(
        executable=settings.ytdlp_executable,
        cookies_file=settings.ytdlp_cookies_file,
    )
    return ArchiveService(
        db=db,
        archive_root=settings.archive_root,
        adapter=adapter,
        max_workers=settings.download_concurrency,
        max_attempts=settings.download_max_attempts,
    )


def cmd_enqueue(args: argparse.Namespace) -> int:
    service = _build_service()
    try:
        try:
            job = service.enqueue(
                args.url,
                quality_preference=args.quality,
                auto_start=not args.sync,
            )
        except DuplicateArchiveError as exc:
            print(json.dumps({"error": exc.code, "message": str(exc)}), file=sys.stderr)
            return 2

        if args.sync:
            # Job was left queued; process it in-process.
            finished = service.process_next_queued()
            payload = finished or service.get_job(job.id)
        else:
            payload = job

        assert payload is not None
        print(
            json.dumps(
                {
                    "id": payload.id,
                    "status": payload.status,
                    "platform_video_id": payload.platform_video_id,
                    "error_code": payload.error_code,
                    "error_message": payload.error_message,
                },
                indent=2,
            )
        )
        return 0 if payload.status in {"queued", "downloading", "completed"} else 1
    except LonesVdlError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}), file=sys.stderr)
        return 1
    finally:
        service.close()
        service.db.close()


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["serve"]

    parser = argparse.ArgumentParser(prog="lones-vdl")
    sub = parser.add_subparsers(dest="command", required=True)

    enqueue = sub.add_parser("enqueue", help="Enqueue a YouTube URL for archival")
    enqueue.add_argument("url", help="YouTube video URL")
    enqueue.add_argument(
        "--quality",
        default="best",
        help="yt-dlp format preference (default: best)",
    )
    enqueue.add_argument(
        "--sync",
        action="store_true",
        help="Process the job in-process and wait for completion",
    )
    enqueue.set_defaults(func=cmd_enqueue)

    serve = sub.add_parser("serve", help="Run the HTTP API")
    serve.set_defaults(func=lambda _args: _serve())

    args = parser.parse_args(argv)
    result = args.func(args)
    return int(result) if result is not None else 0


def _serve() -> int:
    import uvicorn

    from lones_vdl.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "lones_vdl.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
