"""Filter presets for browsing the library: tags to require and tags to hide.

Stored as one JSON document in app_settings, so they travel with `state export`. One preset
can be the default; browse views apply it unless the user picks another or turns it off."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session as DbSession

from lones_vdl.services import settings_store, tags

SETTING_KEY = "library.presets"
MAX_PRESETS = 50


class PresetError(Exception):
    pass


@dataclass
class Preset:
    id: int
    name: str
    include: list[str] = field(default_factory=list)  # a video must have all of these
    exclude: list[str] = field(default_factory=list)  # a video must have none of these


@dataclass
class PresetBook:
    presets: list[Preset] = field(default_factory=list)
    default_id: int | None = None
    next_id: int = 1

    def get(self, preset_id: int | None) -> Preset | None:
        return next((p for p in self.presets if p.id == preset_id), None)

    @property
    def default(self) -> Preset | None:
        return self.get(self.default_id)


def load(db: DbSession) -> PresetBook:
    raw = settings_store.get(db, SETTING_KEY)
    if not raw:
        return PresetBook()
    data = json.loads(raw)
    return PresetBook(
        presets=[Preset(**p) for p in data.get("presets", [])],
        default_id=data.get("default_id"),
        next_id=data.get("next_id", 1),
    )


def _save(db: DbSession, book: PresetBook) -> None:
    settings_store.put(db, SETTING_KEY, json.dumps(asdict(book)))


def _checked(book: PresetBook, name: str, include: list[str], exclude: list[str], own_id=None):
    name = " ".join(name.split())
    if not name:
        raise PresetError("a preset needs a name")
    if any(p.name.lower() == name.lower() and p.id != own_id for p in book.presets):
        raise PresetError("another preset already has that name")
    return name, tags.clean(include), tags.clean(exclude)


def create(db: DbSession, name: str, include: list[str], exclude: list[str]) -> Preset:
    book = load(db)
    if len(book.presets) >= MAX_PRESETS:
        raise PresetError("too many presets")
    name, include, exclude = _checked(book, name, include, exclude)
    preset = Preset(book.next_id, name, include, exclude)
    book.next_id += 1
    book.presets.append(preset)
    _save(db, book)
    return preset


def update(db: DbSession, preset_id: int, name: str, include: list[str], exclude: list[str]):
    book = load(db)
    preset = book.get(preset_id)
    if preset is None:
        raise KeyError(preset_id)
    preset.name, preset.include, preset.exclude = _checked(
        book, name, include, exclude, own_id=preset_id
    )
    _save(db, book)
    return preset


def delete(db: DbSession, preset_id: int) -> None:
    book = load(db)
    if book.get(preset_id) is None:
        raise KeyError(preset_id)
    book.presets = [p for p in book.presets if p.id != preset_id]
    if book.default_id == preset_id:
        book.default_id = None
    _save(db, book)


def set_default(db: DbSession, preset_id: int | None) -> None:
    book = load(db)
    if preset_id is not None and book.get(preset_id) is None:
        raise KeyError(preset_id)
    book.default_id = preset_id
    _save(db, book)


def resolve(db: DbSession, selector: str | None) -> Preset | None:
    """Query value -> preset: "default", a preset id, or None/"none" for no preset."""
    if not selector or selector == "none":
        return None
    book = load(db)
    if selector == "default":
        return book.default
    return book.get(int(selector)) if selector.isdecimal() else None
