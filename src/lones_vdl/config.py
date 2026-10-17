"""Application configuration loaded from environment / .env."""

from pathlib import Path

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
    api_token: str = "change-me"
    archive_root: Path = Path("./data/archive")
    database_path: Path = Path("./data/lones_vdl.db")
    ytdlp_cookies_file: Path | None = None
    # Comma-separated platforms whose cookie domains are kept when filtering.
    cookie_platforms: str = "youtube,twitch"
    ytdlp_executable: str = "yt-dlp"
    download_concurrency: int = 1
    download_max_attempts: int = 3
    default_quality: str = "best"
    # Hours between automatic checks of channels with watch enabled (0 disables).
    channel_watch_interval_hours: float = 6.0
    # Built Svelte UI (web/dist). Empty/unset → auto-detect common locations.
    web_dist: Path | None = None

    def cookie_platform_list(self) -> list[str]:
        return [p.strip().lower() for p in self.cookie_platforms.split(",") if p.strip()]


def get_settings() -> Settings:
    return Settings()


def resolve_web_dist(settings: Settings | None = None) -> Path | None:
    """Return directory of built web UI, or None if not present."""
    cfg = settings or get_settings()
    if cfg.web_dist is not None:
        path = Path(cfg.web_dist)
        return path if path.is_dir() else None

    # Repo checkout: src/lones_vdl/app.py → parents[2] == repo root
    repo_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    docker_dist = Path("/app/web/dist")
    for candidate in (repo_dist, docker_dist):
        if candidate.is_dir():
            return candidate
    return None
