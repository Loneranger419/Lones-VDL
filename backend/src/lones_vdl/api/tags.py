"""Tags found on archived videos."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from lones_vdl.api.deps import AuthDep, DbDep
from lones_vdl.schemas import TagOut
from lones_vdl.services import tags

router = APIRouter(prefix="/tags", tags=["tags"], dependencies=[AuthDep])


@router.get("", response_model=list[TagOut])
def list_tags(
    db: DbDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
):
    """Most used first; `q` keeps tags containing that text."""
    return [
        TagOut(tag=tag, label=label, videos=count)
        for tag, label, count in tags.popular(db, q, limit)
    ]
