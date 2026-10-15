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


def get_settings() -> Settings:
    return Settings()
