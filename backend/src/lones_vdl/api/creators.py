from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from lones_vdl.api.deps import AuthDep, DbDep
from lones_vdl.db.models import Creator
from lones_vdl.schemas import CreatorIn, CreatorOut, CreatorUpdate
from lones_vdl.services import creators as creator_service

router = APIRouter(prefix="/creators", tags=["creators"], dependencies=[AuthDep])


def _get(db, creator_pk: int) -> Creator:
    creator = db.get(Creator, creator_pk)
    if creator is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "creator not found")
    return creator


def _out(db, creator: Creator) -> CreatorOut:
    return CreatorOut.model_validate(creator_service.listing(db, [creator])[0])


@router.get("", response_model=list[CreatorOut])
def list_creators(db: DbDep):
    return creator_service.listing(db)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CreatorOut)
def create_creator(body: CreatorIn, db: DbDep):
    if creator_service.name_taken(db, body.name):
        raise HTTPException(status.HTTP_409_CONFLICT, "a creator with that name exists")
    creator = Creator(name=body.name.strip(), notes=body.notes)
    db.add(creator)
    try:
        creator_service.set_channels(db, creator, body.channel_ids)
    except creator_service.CreatorError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    return _out(db, creator)


@router.get("/{creator_pk}", response_model=CreatorOut)
def get_creator(creator_pk: int, db: DbDep):
    return _out(db, _get(db, creator_pk))


@router.patch("/{creator_pk}", response_model=CreatorOut)
def update_creator(creator_pk: int, body: CreatorUpdate, db: DbDep):
    creator = _get(db, creator_pk)
    if body.name is not None:
        if creator_service.name_taken(db, body.name, exclude=creator.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "a creator with that name exists")
        creator.name = body.name.strip()
    if "notes" in body.model_fields_set:
        creator.notes = body.notes
    if body.channel_ids is not None:
        try:
            creator_service.set_channels(db, creator, body.channel_ids)
        except creator_service.CreatorError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    return _out(db, creator)


@router.delete("/{creator_pk}", status_code=status.HTTP_204_NO_CONTENT)
def delete_creator(creator_pk: int, db: DbDep) -> None:
    """Channels and videos stay; they are just unlinked."""
    creator = _get(db, creator_pk)
    for channel in list(creator.channels):
        channel.creator = None
    db.delete(creator)
    db.commit()
