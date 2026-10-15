"""Integration tests for archive orchestration with a fake yt-dlp adapter."""

from __future__ import annotations

import json

import pytest
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.errors import DuplicateArchiveError, PermanentDownloadError, TransientDownloadError
from lones_vdl.platform.ytdlp import parse_youtube_id


def test_parse_youtube_id() -> None:
    assert parse_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_id("https://example.com/") is None


def test_successful_archive(service, tmp_env, fake_adapter) -> None:
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    job = service.enqueue(url, auto_start=False)
    finished = service.process_next_queued()
    assert finished is not None
    assert finished.status == "completed"
    assert finished.platform_video_id == "dQw4w9WgXcQ"
    assert fake_adapter.download_calls == 1

    video = service.get_video("youtube", "dQw4w9WgXcQ")
    assert video is not None
    assert video.checksum_sha256
    media = tmp_env.archive_root / video.media_relpath
    assert media.is_file()
    meta = tmp_env.archive_root / video.metadata_relpath
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["source"]["id"] == "dQw4w9WgXcQ"
    assert payload["archive"]["job_id"] == job.id
    assert (tmp_env.archive_root / "youtube" / "dQw4w9WgXcQ" / "thumbnails" / "thumb.jpg").is_file()


def test_duplicate_rejected_on_enqueue(service) -> None:
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    service.enqueue(url, auto_start=False)
    service.process_next_queued()
    with pytest.raises(DuplicateArchiveError):
        service.enqueue(url, auto_start=False)


def test_permanent_failure(tmp_env) -> None:
    from lones_vdl.db import Database
    from lones_vdl.download.service import ArchiveService

    adapter = FakeYtdlpAdapter(fail_extract=PermanentDownloadError("gone"))
    db = Database(tmp_env.database_path)
    svc = ArchiveService(db=db, archive_root=tmp_env.archive_root, adapter=adapter)
    try:
        svc.enqueue("https://www.youtube.com/watch?v=dQw4w9WgXcQ", auto_start=False)
        finished = svc.process_next_queued()
        assert finished is not None
        assert finished.status == "failed"
        assert finished.error_code == "unavailable"
    finally:
        svc.close()
        db.close()


def test_transient_retries_then_fails(tmp_env) -> None:
    from lones_vdl.db import Database
    from lones_vdl.download.service import ArchiveService

    adapter = FakeYtdlpAdapter(fail_download=TransientDownloadError("rate limited"))
    db = Database(tmp_env.database_path)
    svc = ArchiveService(
        db=db,
        archive_root=tmp_env.archive_root,
        adapter=adapter,
        max_attempts=2,
    )
    try:
        svc.enqueue("https://www.youtube.com/watch?v=dQw4w9WgXcQ", auto_start=False)
        first = svc.process_next_queued()
        assert first is not None
        assert first.status == "queued"
        second = svc.process_next_queued()
        assert second is not None
        assert second.status == "failed"
        assert second.error_code == "transient"
        assert second.attempts == 2
    finally:
        svc.close()
        db.close()
