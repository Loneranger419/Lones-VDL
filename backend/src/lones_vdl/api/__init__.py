"""HTTP API routers. Keep routers thin: validate, call services, return schemas."""

from fastapi import APIRouter

from lones_vdl.api import auth, events, health, jobs, system, videos

router = APIRouter(prefix="/api")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(jobs.router)
router.include_router(events.router)
router.include_router(videos.router)
router.include_router(system.router)
