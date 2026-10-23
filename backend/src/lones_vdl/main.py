"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from lones_vdl import __version__, api
from lones_vdl.config import Settings, get_settings
from lones_vdl.spa import mount_spa

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Lones-VDL", version=__version__)
    app.state.settings = settings
    app.include_router(api.router)

    dist = settings.resolve_frontend_dist()
    if dist is not None:
        mount_spa(app, dist)
    else:
        logger.warning("frontend build not found; serving API only")
    return app
