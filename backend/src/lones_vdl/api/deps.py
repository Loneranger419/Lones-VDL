from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DbSession

from lones_vdl.db.models import Session
from lones_vdl.services import auth
from lones_vdl.state import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


def get_db(services: ServicesDep) -> Iterator[DbSession]:
    """One session per request, committed on success as a safety net. Routes whose effects
    must be visible before the response (cookies, worker wake-ups) call db.commit() first."""
    with services.sessions() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()


DbDep = Annotated[DbSession, Depends(get_db)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_session(request: Request, db: DbDep, services: ServicesDep) -> Session:
    token = request.cookies.get(auth.SESSION_COOKIE)
    session = auth.get_session(db, token, session_days=services.settings.session_days)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    return session


AuthDep = Depends(require_session)
