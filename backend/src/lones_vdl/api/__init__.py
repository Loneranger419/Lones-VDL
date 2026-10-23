"""HTTP API routers. Keep routers thin: validate, call services, return schemas."""

from fastapi import APIRouter

from lones_vdl.api import (
    auth,
    channels,
    collections,
    cookies,
    creators,
    events,
    health,
    jobs,
    settings,
    system,
    videos,
)

router = APIRouter(prefix="/api")
for module in (
    health,
    auth,
    jobs,
    events,
    videos,
    channels,
    creators,
    collections,
    cookies,
    settings,
    system,
):
    router.include_router(module.router)
