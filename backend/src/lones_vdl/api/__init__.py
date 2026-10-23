"""HTTP API routers. Keep routers thin: validate, call services, return schemas."""

from fastapi import APIRouter

from lones_vdl.api import health

router = APIRouter(prefix="/api")
router.include_router(health.router)
