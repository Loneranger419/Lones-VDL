"""Cookie jar from the web UI. Uploads are a raw text body (no multipart dependency).
Responses carry cookie names and expiry dates only, never values."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from lones_vdl.api.deps import AuthDep, DbDep, ServicesDep
from lones_vdl.schemas import CookieHealth, CookieImportOut, CookieStatus
from lones_vdl.services import cookies as cookie_service
from lones_vdl.services import jobs as job_service
from lones_vdl.state import Services

router = APIRouter(prefix="/cookies", tags=["cookies"], dependencies=[AuthDep])


@router.get("", response_model=CookieStatus)
def cookie_status(db: DbDep, services: ServicesDep):
    return cookie_service.status(services.settings, db)


@router.post(
    "",
    response_model=CookieImportOut,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"text/plain": {"schema": {"type": "string"}}},
            "description": "Netscape cookies.txt export (other sites' cookies are dropped)",
        }
    },
)
async def import_cookies(request: Request, services: ServicesDep):
    """Replace the cookie jar, then retry jobs that failed for lack of valid cookies."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > cookie_service.MAX_IMPORT_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "cookie file too large")
    text = data.decode("utf-8-sig", errors="replace")
    return await run_in_threadpool(_import, services, text)


def _import(services: Services, text: str) -> CookieImportOut:
    try:
        summary = cookie_service.import_cookies(services.settings, text)
    except cookie_service.CookieImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    with services.sessions.begin() as db:
        cookie_service.record_health(db, cookie_service.UNTESTED)
        requeued = job_service.requeue_cookie_failures(db)
    for job in requeued:
        services.bus.publish("job", job_service.job_payload(job))
    if requeued:
        services.worker.wake()
    with services.sessions() as db:
        current = cookie_service.status(services.settings, db)
    return CookieImportOut(
        status=current,
        summary=cookie_service.summary_payload(summary),
        requeued_jobs=len(requeued),
    )


@router.post("/test", response_model=CookieHealth)
async def test_cookies(services: ServicesDep):
    """Resolve an age-restricted video with the current cookies (no media download)."""
    health, detail = await run_in_threadpool(cookie_service.test, services.settings, services.ytdlp)

    def save() -> CookieHealth:
        with services.sessions.begin() as db:
            return cookie_service.record_health(db, health, detail)

    return await run_in_threadpool(save)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_cookies(db: DbDep, services: ServicesDep) -> None:
    cookie_service.delete(services.settings, db)
    db.commit()
