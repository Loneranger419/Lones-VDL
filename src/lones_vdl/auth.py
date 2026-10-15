"""API bearer-token authentication."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lones_vdl.config import Settings

_bearer = HTTPBearer(auto_error=False)


def make_require_api_token(settings: Settings) -> Callable[..., None]:
    async def _require(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
    ) -> None:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if credentials.credentials != settings.api_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return _require
