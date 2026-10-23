"""Settings editable from the UI. Environment values are defaults; edits are stored in the DB."""

from __future__ import annotations

import json
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.services import settings_store
from lones_vdl.ytdlp import QUALITIES

RUNTIME_KEY = "runtime.overrides"


class RuntimeSettings(BaseModel):
    default_quality: str
    download_concurrency: int = Field(ge=1, le=8)
    channel_watch_interval_hours: float = Field(ge=0, description="0 disables channel checks")
    ytdlp_channel: Literal["stable", "nightly"]
    ytdlp_update_interval_hours: float = Field(ge=0, description="0 disables auto-update")

    @field_validator("default_quality")
    @classmethod
    def _quality(cls, value: str) -> str:
        if value not in QUALITIES:
            raise ValueError(f"must be one of {', '.join(QUALITIES)}")
        return value


class RuntimeUpdate(BaseModel):
    """PATCH body: only the fields sent are changed (validated against RuntimeSettings)."""

    default_quality: str | None = None
    download_concurrency: int | None = None
    channel_watch_interval_hours: float | None = None
    ytdlp_channel: Literal["stable", "nightly"] | None = None
    ytdlp_update_interval_hours: float | None = None


class RuntimeConfig:
    def __init__(self, settings: Settings, sessions: sessionmaker) -> None:
        self.settings = settings
        self.sessions = sessions
        self._lock = threading.Lock()
        self._overrides: dict[str, Any] = {}
        with sessions() as db:
            raw = settings_store.get(db, RUNTIME_KEY)
        if raw:
            self._overrides = json.loads(raw)
        self._current = self._merge(self._overrides)

    def defaults(self) -> dict[str, Any]:
        s = self.settings
        return {
            "default_quality": s.default_quality,
            "download_concurrency": s.download_concurrency,
            "channel_watch_interval_hours": s.channel_watch_interval_hours,
            "ytdlp_channel": s.ytdlp_channel,
            "ytdlp_update_interval_hours": s.ytdlp_update_interval_hours,
        }

    def _merge(self, overrides: dict[str, Any]) -> RuntimeSettings:
        known = {k: v for k, v in overrides.items() if k in RuntimeSettings.model_fields}
        return RuntimeSettings(**{**self.defaults(), **known})

    @property
    def current(self) -> RuntimeSettings:
        return self._current

    def update(self, changes: dict[str, Any]) -> RuntimeSettings:
        """Validate and persist; raises pydantic.ValidationError on bad values."""
        with self._lock:
            overrides = {**self._overrides, **changes}
            merged = self._merge(overrides)  # validates
            with self.sessions.begin() as db:
                settings_store.put(db, RUNTIME_KEY, json.dumps(overrides))
            self._overrides = overrides
            self._current = merged
            return merged
