from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from lones_vdl.api.deps import AuthDep, DbDep
from lones_vdl.db.models import Collection
from lones_vdl.schemas import (
    CollectionDetail,
    CollectionIn,
    CollectionOut,
    CollectionUpdate,
    VideoIds,
)
from lones_vdl.services import collections as collection_service

router = APIRouter(prefix="/collections", tags=["collections"], dependencies=[AuthDep])


def _get(db, collection_pk: int) -> Collection:
    collection = db.get(Collection, collection_pk)
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "collection not found")
    return collection


@router.get("", response_model=list[CollectionOut])
def list_collections(db: DbDep):
    return collection_service.summaries(db)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CollectionDetail)
def create_collection(body: CollectionIn, db: DbDep):
    collection = Collection(name=body.name.strip(), description=body.description)
    db.add(collection)
    db.commit()
    return collection_service.detail(db, collection)


@router.get("/{collection_pk}", response_model=CollectionDetail)
def get_collection(collection_pk: int, db: DbDep):
    return collection_service.detail(db, _get(db, collection_pk))


@router.patch("/{collection_pk}", response_model=CollectionDetail)
def update_collection(collection_pk: int, body: CollectionUpdate, db: DbDep):
    collection = _get(db, collection_pk)
    if body.name is not None:
        collection.name = body.name.strip()
    if "description" in body.model_fields_set:
        collection.description = body.description
    db.commit()
    return collection_service.detail(db, collection)


@router.delete("/{collection_pk}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(collection_pk: int, db: DbDep) -> None:
    """Deletes the list only; the videos stay archived."""
    db.delete(_get(db, collection_pk))
    db.commit()


@router.post("/{collection_pk}/items", response_model=CollectionDetail)
def add_items(collection_pk: int, body: VideoIds, db: DbDep):
    """Append videos (already-present ones are skipped)."""
    collection = _get(db, collection_pk)
    try:
        collection_service.add_items(db, collection, body.video_ids)
    except collection_service.CollectionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    return collection_service.detail(db, collection)


@router.put("/{collection_pk}/items", response_model=CollectionDetail)
def reorder_items(collection_pk: int, body: VideoIds, db: DbDep):
    """Set the order; video_ids must list every item exactly once."""
    collection = _get(db, collection_pk)
    try:
        collection_service.reorder(collection, body.video_ids)
    except collection_service.CollectionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    return collection_service.detail(db, collection)


@router.delete("/{collection_pk}/items/{video_pk}", response_model=CollectionDetail)
def remove_item(collection_pk: int, video_pk: int, db: DbDep):
    collection = _get(db, collection_pk)
    if not collection_service.remove_item(collection, video_pk):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "video is not in this collection")
    db.commit()
    return collection_service.detail(db, collection)
