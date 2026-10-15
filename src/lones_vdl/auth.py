"""API bearer-token authentication (header or query for media elements)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lones_vdl.config import Settings

_bearer = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    token: str | None,
) -> str | None:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    if token:
        return token
    # Optional cookie for future use
    cookie = request.cookies.get("lones_vdl_token")
    return cookie


def make_require_api_token(settings: Settings) -> Callable[..., None]:
    async def _require(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
        token: str | None = Query(default=None, description="API token for media URLs"),
    ) -> None:
        provided = _extract_token(request, credentials, token)
        if not provided:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if provided != settings.api_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return _require
