"""Shared fixtures for Milestone 1 tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from lones_vdl.config import Settings
from lones_vdl.db import Database
from lones_vdl.download.service import ArchiveService
from lones_vdl.platform.ytdlp import DownloadResult, VideoInfo


class FakeYtdlpAdapter:
    def __init__(
        self,
        *,
        video_id: str = "dQw4w9WgXcQ",
        title: str = "Test Video",
        fail_extract: Exception | None = None,
        fail_download: Exception | None = None,
    ) -> None:
        self.video_id = video_id
        self.title = title
        self.fail_extract = fail_extract
        self.fail_download = fail_download
        self.extract_calls = 0
        self.download_calls = 0

    def extract_info(self, url: str) -> VideoInfo:
        self.extract_calls += 1
        if self.fail_extract is not None:
            raise self.fail_extract
        return VideoInfo(
            platform="youtube",
            video_id=self.video_id,
            url=url,
            title=self.title,
            raw={
                "id": self.video_id,
                "title": self.title,
                "webpage_url": url,
                "channel": "Test Channel",
                "duration": 42,
            },
        )

    def download(
        self,
        url: str,
        *,
        output_dir: Path,
        quality_preference: str,
    ) -> DownloadResult:
        self.download_calls += 1
        if self.fail_download is not None:
            raise self.fail_download
        info = VideoInfo(
            platform="youtube",
            video_id=self.video_id,
            url=url,
            title=self.title,
            raw={
                "id": self.video_id,
                "title": self.title,
                "webpage_url": url,
                "channel": "Test Channel",
                "duration": 42,
            },
        )
        media_path = output_dir / "media.mkv"
        media_path.write_bytes(b"fake-video-bytes")
        thumb = output_dir / "thumb.jpg"
        thumb.write_bytes(b"fake-thumb")
        return DownloadResult(
            info=info,
            media_path=media_path,
            thumbnail_paths=[thumb],
            subtitle_paths=[],
            ytdlp_version="test-ytdlp",
        )


@pytest.fixture
def tmp_env(tmp_path: Path) -> Settings:
    archive = tmp_path / "archive"
    db_path = tmp_path / "test.db"
    archive.mkdir()
    return Settings(
        api_token="test-token",
        archive_root=archive,
        database_path=db_path,
        download_concurrency=1,
        download_max_attempts=2,
    )


@pytest.fixture
def fake_adapter() -> FakeYtdlpAdapter:
    return FakeYtdlpAdapter()


@pytest.fixture
def service(tmp_env: Settings, fake_adapter: FakeYtdlpAdapter) -> ArchiveService:
    db = Database(tmp_env.database_path)
    svc = ArchiveService(
        db=db,
        archive_root=tmp_env.archive_root,
        adapter=fake_adapter,
        max_workers=1,
        max_attempts=tmp_env.download_max_attempts,
    )
    yield svc
    svc.close()
    db.close()
