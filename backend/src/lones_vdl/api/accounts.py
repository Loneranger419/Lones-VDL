"""Accounts: the identities yt-dlp may sign in with, each with its own cookies.

Uploads are a raw text body (no multipart dependency). Responses carry cookie names and
expiry dates only, never values."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from lones_vdl.api.deps import AuthDep, DbDep, ServicesDep
from lones_vdl.db.models import Account, AccountRole, AttemptKind
from lones_vdl.schemas import (
    AccountCreate,
    AccountImportOut,
    AccountOut,
    AccountUpdate,
    CookieHealth,
)
from lones_vdl.services import accounts as account_service
from lones_vdl.services import cookies as cookie_service
from lones_vdl.services import jobs as job_service
from lones_vdl.state import Services
from lones_vdl.ytdlp import ErrorKind

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[AuthDep])


def _get(db, account_id: int) -> Account:
    account = account_service.get(db, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    return account


def _out(services: Services, account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        label=account.label,
        role=account.role,  # type: ignore[arg-type]
        enabled=account.enabled,
        created_at=account.created_at,
        status=account_service.status(services.settings, account),
    )


@router.get("", response_model=list[AccountOut])
def list_accounts(db: DbDep, services: ServicesDep):
    return [_out(services, a) for a in account_service.list_accounts(db)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AccountOut)
def create_account(body: AccountCreate, db: DbDep, services: ServicesDep):
    try:
        account = account_service.create(db, body.label, body.role)
    except account_service.AccountError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return _out(services, account)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountUpdate, db: DbDep, services: ServicesDep):
    account = _get(db, account_id)
    if body.label is not None and body.label.strip() != account.label:
        try:
            account_service.rename(db, account, body.label)
        except account_service.AccountError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if body.enabled is not None:
        account.enabled = body.enabled
    db.commit()
    return _out(services, account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int, db: DbDep, services: ServicesDep) -> None:
    account = _get(db, account_id)
    account_service.remove(services.settings, db, account)
    db.commit()


@router.post(
    "/{account_id}/cookies",
    response_model=AccountImportOut,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"text/plain": {"schema": {"type": "string"}}},
            "description": "Netscape cookies.txt export (other sites' cookies are dropped)",
        }
    },
)
async def import_cookies(account_id: int, request: Request, services: ServicesDep):
    """Replace this account's cookies, then retry jobs that failed for lack of them."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > cookie_service.MAX_IMPORT_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "cookie file too large")
    text = data.decode("utf-8-sig", errors="replace")
    return await run_in_threadpool(_import, services, account_id, text)


def _import(services: Services, account_id: int, text: str) -> AccountImportOut:
    with services.sessions.begin() as db:
        account = _get(db, account_id)
        try:
            summary = account_service.import_cookies(services.settings, account, text)
        except cookie_service.CookieImportError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        # A personal account can also fix members-only videos that had nowhere to go.
        extra = (str(ErrorKind.MEMBERS_ONLY),) if account.role == AccountRole.PERSONAL else ()
        requeued = job_service.requeue_cookie_failures(db, extra)
    for job in requeued:
        services.bus.publish("job", job_service.job_payload(job))
    if requeued:
        services.worker.wake()
    with services.sessions() as db:
        out = _out(services, _get(db, account_id))
    return AccountImportOut(
        account=out, summary=cookie_service.summary_payload(summary), requeued_jobs=len(requeued)
    )


@router.delete("/{account_id}/cookies", status_code=status.HTTP_204_NO_CONTENT)
def delete_cookies(account_id: int, db: DbDep, services: ServicesDep) -> None:
    account_service.delete_cookies(services.settings, _get(db, account_id))
    db.commit()


@router.post("/{account_id}/test", response_model=CookieHealth)
async def test_account(account_id: int, services: ServicesDep):
    """Resolve an age-restricted video with this account (no media download)."""

    def run() -> CookieHealth:
        with services.sessions() as db:
            account = _get(db, account_id)
            path = account_service.cookie_path(services.settings, account)
        with services.policy.attempt(None, account, AttemptKind.TEST):
            health, detail = cookie_service.test(services.settings, services.ytdlp, path)
        with services.sessions.begin() as db:
            account = _get(db, account_id)
            account_service.record_health(account, health, detail)
            return account_service.health(account)  # type: ignore[return-value]

    return await run_in_threadpool(run)
