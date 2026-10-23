from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from lones_vdl.api.deps import DbDep, ServicesDep, client_ip
from lones_vdl.schemas import AuthStatus, PasswordChange, PasswordRequest
from lones_vdl.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, token: str, *, remember: bool, services) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=services.settings.session_days * 86400 if remember else None,
        httponly=True,
        samesite="strict",
        secure=services.settings.cookie_secure,
        path="/",
    )


@router.get("/status")
def auth_status(request: Request, db: DbDep, services: ServicesDep) -> AuthStatus:
    token = request.cookies.get(auth.SESSION_COOKIE)
    session = auth.get_session(db, token, session_days=services.settings.session_days)
    return AuthStatus(setup_required=not auth.password_is_set(db), authenticated=bool(session))


@router.post("/setup", status_code=status.HTTP_204_NO_CONTENT)
def setup(
    body: PasswordRequest, request: Request, response: Response, db: DbDep, services: ServicesDep
) -> None:
    """First run only: choose the admin password."""
    if auth.password_is_set(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "password already set")
    try:
        auth.set_password(db, body.password)
    except auth.PasswordPolicyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    token = auth.create_session(
        db,
        remember=body.remember,
        session_days=services.settings.session_days,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    db.commit()
    _set_cookie(response, token, remember=body.remember, services=services)


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(
    body: PasswordRequest, request: Request, response: Response, db: DbDep, services: ServicesDep
) -> None:
    ip = client_ip(request)
    wait = services.throttle.retry_after(ip)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"too many attempts; try again in {int(wait) + 1}s",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    if not auth.verify_password(db, body.password):
        services.throttle.failure(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong password")
    services.throttle.success(ip)
    auth.purge_expired(db)
    token = auth.create_session(
        db,
        remember=body.remember,
        session_days=services.settings.session_days,
        user_agent=request.headers.get("user-agent"),
        ip=ip,
    )
    db.commit()
    _set_cookie(response, token, remember=body.remember, services=services)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbDep) -> None:
    auth.delete_session(db, request.cookies.get(auth.SESSION_COOKIE))
    db.commit()
    response.delete_cookie(auth.SESSION_COOKIE, path="/")


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange, request: Request, response: Response, db: DbDep, services: ServicesDep
) -> None:
    """Change the password (signs out every other device; this one stays signed in)."""
    if (
        auth.get_session(
            db,
            request.cookies.get(auth.SESSION_COOKIE),
            session_days=services.settings.session_days,
        )
        is None
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    if not auth.verify_password(db, body.current_password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "current password is wrong")
    try:
        auth.set_password(db, body.new_password)
    except auth.PasswordPolicyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    token = auth.create_session(
        db,
        remember=True,
        session_days=services.settings.session_days,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    db.commit()
    _set_cookie(response, token, remember=True, services=services)
