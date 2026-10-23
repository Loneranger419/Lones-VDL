"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lones_vdl import __version__, api
from lones_vdl.config import Settings, get_settings
from lones_vdl.spa import mount_spa
from lones_vdl.state import Services

logger = logging.getLogger(__name__)

# State-changing API calls must carry this header. Browsers cannot add custom headers to
# cross-site form posts, so together with SameSite=Strict cookies this blocks CSRF.
CSRF_HEADER = "x-lones-vdl"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _configure_logging(level: str) -> None:
    """uvicorn configures only its own loggers; give ours a handler at the same level."""
    app_logger = logging.getLogger("lones_vdl")
    app_logger.setLevel(level.upper())
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        app_logger.addHandler(handler)
        app_logger.propagate = False


def create_app(settings: Settings | None = None, *, ytdlp_command: list[str] | None = None):
    settings = settings or get_settings()
    _configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = Services.build(settings, ytdlp_command=ytdlp_command)
        app.state.services = services
        await services.start()
        try:
            yield
        finally:
            await services.stop()

    app = FastAPI(title="Lones-VDL", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        if (
            request.method not in _SAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": f"missing {CSRF_HEADER} header"}, status_code=403)
        return await call_next(request)

    app.include_router(api.router)

    dist = settings.resolve_frontend_dist()
    if dist is not None:
        mount_spa(app, dist)
    else:
        logger.warning("frontend build not found; serving API only")
    return app
