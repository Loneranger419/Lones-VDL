"""Settings editable from the UI. Environment values are defaults; edits are stored in the DB."""

from __future__ import annotations

import json
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import sessionmaker

from lones_vdl.config import Settings
from lones_vdl.services import policy, settings_store
from lones_vdl.ytdlp import QUALITIES

RUNTIME_KEY = "runtime.overrides"


class RuntimeSettings(BaseModel):
    default_quality: str
    channel_watch_interval_hours: float = Field(ge=0, description="0 disables channel checks")
    ytdlp_channel: Literal["stable", "nightly"]
    ytdlp_update_interval_hours: float = Field(ge=0, description="0 disables auto-update")
    daily_download_cap: int = Field(
        ge=1, description="videos that start downloading per rolling 24 hours"
    )
    daily_auth_cap: int = Field(
        ge=0, description="of those, how many may use an account (0 = anonymous only)"
    )
    video_delay_min_seconds: float = Field(description="shortest pause between videos")
    video_delay_max_seconds: float = Field(description="longest pause between videos")

    @field_validator("default_quality")
    @classmethod
    def _quality(cls, value: str) -> str:
        if value not in QUALITIES:
            raise ValueError(f"must be one of {', '.join(QUALITIES)}")
        return value

    @model_validator(mode="after")
    def _delays(self) -> RuntimeSettings:
        low, high = self.video_delay_min_seconds, self.video_delay_max_seconds
        if not policy.DELAY_FLOOR <= low <= high <= policy.DELAY_CEIL:
            raise ValueError(
                f"video delays must satisfy {policy.DELAY_FLOOR:g} <= min <= max "
                f"<= {policy.DELAY_CEIL:g} seconds"
            )
        return self


class RuntimeUpdate(BaseModel):
    """PATCH body: only the fields sent are changed (validated against RuntimeSettings)."""

    default_quality: str | None = None
    channel_watch_interval_hours: float | None = None
    ytdlp_channel: Literal["stable", "nightly"] | None = None
    ytdlp_update_interval_hours: float | None = None
    daily_download_cap: int | None = None
    daily_auth_cap: int | None = None
    video_delay_min_seconds: float | None = None
    video_delay_max_seconds: float | None = None


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
            "channel_watch_interval_hours": s.channel_watch_interval_hours,
            "ytdlp_channel": s.ytdlp_channel,
            "ytdlp_update_interval_hours": s.ytdlp_update_interval_hours,
            "daily_download_cap": s.daily_download_cap,
            "daily_auth_cap": s.daily_auth_cap,
            "video_delay_min_seconds": s.video_delay_min_seconds,
            "video_delay_max_seconds": s.video_delay_max_seconds,
        }

    def _merge(self, overrides: dict[str, Any]) -> RuntimeSettings:
        # Unknown keys (e.g. the removed download_concurrency) are dropped.
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
