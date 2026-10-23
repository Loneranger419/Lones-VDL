from fastapi import APIRouter
from pydantic import BaseModel

from lones_vdl import __version__

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    version: str


@router.get("/health")
def health() -> Health:
    """Liveness check. Unauthenticated by design (used by Docker healthcheck)."""
    return Health(status="ok", version=__version__)
