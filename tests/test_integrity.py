"""Tests for checksum verify and archive rescan/import."""

from __future__ import annotations

from pathlib import Path

from lones_vdl.db import Database
from lones_vdl.integrity import rescan_archive, verify_archive
from lones_vdl.storage import item_paths, sha256_file, write_checksums, write_sidecar


def _make_item(
    archive: Path, video_id: str = "abc12345678", payload: bytes = b"video-bytes"
) -> Path:
    paths = item_paths(archive, "youtube", video_id)
    paths.final_dir.mkdir(parents=True)
    media = paths.final_dir / "media.mkv"
    media.write_bytes(payload)
    write_checksums(paths, media)
    write_sidecar(
        paths,
        source={
            "id": video_id,
            "title": "Integrity Test",
            "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        },
        archive={"downloaded_at": "2026-01-01T00:00:00+00:00", "job_id": "test"},
    )
    return media


def test_verify_ok_and_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    db = Database(tmp_path / "test.db")
    media = _make_item(archive)
    rescan_archive(db, archive)

    report = verify_archive(db, archive)
    assert report.checked == 1
    assert report.ok == 1
    assert report.issues == []

    media.write_bytes(b"tampered")
    report2 = verify_archive(db, archive)
    assert report2.ok == 0
    assert report2.issues[0].status == "checksum_mismatch"
    db.close()


def test_rescan_restores_deleted_db_row(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    db = Database(tmp_path / "test.db")
    _make_item(archive, video_id="dQw4w9WgXcQ")
    first = rescan_archive(db, archive)
    assert first.imported == 1
    assert db.get_video("youtube", "dQw4w9WgXcQ") is not None

    assert db.delete_video("youtube", "dQw4w9WgXcQ")
    assert db.get_video("youtube", "dQw4w9WgXcQ") is None

    second = rescan_archive(db, archive)
    assert second.imported == 1
    video = db.get_video("youtube", "dQw4w9WgXcQ")
    assert video is not None
    assert video.title == "Integrity Test"
    assert video.checksum_sha256 == sha256_file(archive / "youtube" / "dQw4w9WgXcQ" / "media.mkv")
    db.close()


def test_verify_flags_not_indexed(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    db = Database(tmp_path / "test.db")
    _make_item(archive, video_id="notInDbYet1")
    report = verify_archive(db, archive)
    assert any(i.status == "not_indexed" for i in report.issues)
    db.close()


def test_verify_missing_on_disk(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    db = Database(tmp_path / "test.db")
    db.insert_video(
        platform="youtube",
        platform_video_id="gone1234567",
        title="Gone",
        url="https://www.youtube.com/watch?v=gone1234567",
        media_relpath="youtube/gone1234567/media.mkv",
        metadata_relpath="youtube/gone1234567/metadata.json",
        checksum_sha256="abc",
    )
    report = verify_archive(db, archive)
    assert report.issues[0].status == "missing_on_disk"
    db.close()
