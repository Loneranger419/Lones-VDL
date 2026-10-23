"""Runtime configuration from ``LONES_VDL_*`` environment variables (and an optional .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LONES_VDL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8080
    log_level: str = "info"
    # Local disk only: database, secrets, yt-dlp venv, job logs. Never on a network share.
    data_dir: Path = Path("./data")
    # Media + sidecars. May be a network share (CIFS/NFS) in production.
    archive_root: Path = Path("./data/archive")
    # Built SvelteKit app. Unset → auto-detect the repo build or the Docker image path.
    frontend_dist: Path | None = None

    # Auth
    session_days: int = Field(default=90, ge=1)
    # Set when served over HTTPS (e.g. behind a reverse proxy); plain-HTTP LAN needs False.
    cookie_secure: bool = False

    # Downloads
    download_concurrency: int = Field(default=1, ge=1, le=8)
    download_max_attempts: int = Field(default=3, ge=1)
    default_quality: str = "best"

    # yt-dlp. Normally a managed venv under data_dir/ytdlp, kept current by the app.
    # Set ytdlp_executable to use an existing install instead (disables managed updates).
    ytdlp_executable: str | None = None
    ytdlp_channel: Literal["stable", "nightly"] = "stable"
    ytdlp_update_interval_hours: float = Field(default=24.0, ge=0)
    # Unset → $UV (exported by `uv run`) or `uv` on PATH.
    uv_executable: str | None = None

    @property
    def database_path(self) -> Path:
        return self.data_dir / "lones_vdl.db"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def cookies_file(self) -> Path:
        return self.secrets_dir / "cookies.txt"

    @property
    def ytdlp_dir(self) -> Path:
        return self.data_dir / "ytdlp"

    @property
    def job_logs_dir(self) -> Path:
        return self.data_dir / "logs" / "jobs"

    @property
    def partial_dir(self) -> Path:
        # On the archive filesystem so promotion is a same-filesystem rename.
        return self.archive_root / ".partial"

    def resolve_frontend_dist(self) -> Path | None:
        candidates = (
            [self.frontend_dist]
            if self.frontend_dist is not None
            else [
                # backend/src/lones_vdl/config.py → repo root is parents[3]
                Path(__file__).resolve().parents[3] / "frontend" / "build",
                Path("/app/frontend"),
            ]
        )
        for path in candidates:
            if (path / "index.html").is_file():
                return path
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
