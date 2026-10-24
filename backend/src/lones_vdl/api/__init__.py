"""HTTP API routers. Keep routers thin: validate, call services, return schemas."""

from fastapi import APIRouter

from lones_vdl.api import (
    accounts,
    auth,
    channels,
    collections,
    creators,
    events,
    health,
    jobs,
    policy,
    presets,
    settings,
    system,
    tags,
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
    accounts,
    policy,
    presets,
    tags,
    settings,
    system,
):
    router.include_router(module.router)
