"""Download policy status: use against the limits, pause state, anonymous success rate."""

from __future__ import annotations

from fastapi import APIRouter

from lones_vdl.api.deps import AuthDep, DbDep, ServicesDep
from lones_vdl.schemas import PolicyStatus

router = APIRouter(prefix="/policy", tags=["policy"], dependencies=[AuthDep])


@router.get("", response_model=PolicyStatus)
def policy_status(db: DbDep, services: ServicesDep):
    return services.policy.status(db)
