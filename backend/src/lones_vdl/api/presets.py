"""Library filter presets (tags to require or hide) and which one applies by default."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from lones_vdl.api.deps import AuthDep, DbDep
from lones_vdl.schemas import DefaultPresetIn, PresetBookOut, PresetIn, PresetOut
from lones_vdl.services import presets

router = APIRouter(prefix="/presets", tags=["presets"], dependencies=[AuthDep])


def _book(db) -> PresetBookOut:
    book = presets.load(db)
    return PresetBookOut(
        presets=[PresetOut(**vars(p)) for p in book.presets], default_id=book.default_id
    )


def _failed(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "preset not found")
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get("", response_model=PresetBookOut)
def list_presets(db: DbDep):
    return _book(db)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PresetOut)
def create_preset(body: PresetIn, db: DbDep):
    try:
        return PresetOut(**vars(presets.create(db, body.name, body.include, body.exclude)))
    except presets.PresetError as exc:
        raise _failed(exc) from exc


@router.put("/default", response_model=PresetBookOut)
def set_default(body: DefaultPresetIn, db: DbDep):
    try:
        presets.set_default(db, body.preset_id)
    except KeyError as exc:
        raise _failed(exc) from exc
    return _book(db)


@router.put("/{preset_id}", response_model=PresetOut)
def update_preset(preset_id: int, body: PresetIn, db: DbDep):
    try:
        return PresetOut(
            **vars(presets.update(db, preset_id, body.name, body.include, body.exclude))
        )
    except (KeyError, presets.PresetError) as exc:
        raise _failed(exc) from exc


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(preset_id: int, db: DbDep) -> Response:
    try:
        presets.delete(db, preset_id)
    except KeyError as exc:
        raise _failed(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
