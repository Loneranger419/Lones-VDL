"""Settings editable from the UI (environment values are the defaults)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ValidationError

from lones_vdl.api.deps import AuthDep, ServicesDep
from lones_vdl.services.runtime import RuntimeSettings, RuntimeUpdate

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[AuthDep])


class SettingsOut(BaseModel):
    current: RuntimeSettings
    defaults: dict[str, Any]


def _out(services) -> SettingsOut:
    return SettingsOut(current=services.runtime.current, defaults=services.runtime.defaults())


@router.get("", response_model=SettingsOut)
def get_settings(services: ServicesDep):
    return _out(services)


@router.patch("", response_model=SettingsOut)
def update_settings(body: RuntimeUpdate, services: ServicesDep):
    try:
        services.runtime.update(body.model_dump(exclude_unset=True))
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            exc.errors(include_url=False, include_context=False),
        ) from exc
    # Background loops re-read the values now instead of at their next tick.
    services.worker.wake()
    services.scheduler.wake()
    services.updater.reschedule()
    return _out(services)
