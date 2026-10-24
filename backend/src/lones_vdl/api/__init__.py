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
    accounts,
    policy,
    settings,
    system,
):
    router.include_router(module.router)
