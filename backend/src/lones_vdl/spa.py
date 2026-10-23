"""Serve the built single-page frontend, falling back to index.html for client-side routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def mount_spa(app: FastAPI, dist: Path) -> None:
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            # Vite emits content-hashed files under _app/immutable; cache them forever.
            immutable = "/_app/immutable/" in candidate.as_posix()
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if immutable else {}
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
