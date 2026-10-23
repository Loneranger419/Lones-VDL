"""Serve the built single-page frontend, falling back to index.html for client-side routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Not in every platform's mimetypes table; browsers want the exact type for PWA install.
MEDIA_TYPES = {".webmanifest": "application/manifest+json"}


def mount_spa(app: FastAPI, dist: Path) -> None:
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            # Vite emits content-hashed files under _app/immutable; cache them forever. Everything
            # else (service worker, manifest, icons) revalidates so a new build shows up at once.
            immutable = "/_app/immutable/" in candidate.as_posix()
            cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
            return FileResponse(
                candidate,
                headers={"Cache-Control": cache},
                media_type=MEDIA_TYPES.get(candidate.suffix),
            )
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
