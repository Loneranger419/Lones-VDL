"""Unit tests for archive path helpers."""

from pathlib import Path

from lones_vdl.storage import (
    item_paths,
    prepare_partial_dir,
    promote_partial,
    sha256_file,
    write_checksums,
    write_sidecar,
)


def test_promote_partial_moves_directory(tmp_path: Path) -> None:
    paths = item_paths(tmp_path, "youtube", "abc12345678")
    partial = prepare_partial_dir(paths)
    (partial / "media.mkv").write_bytes(b"data")
    promote_partial(paths)
    assert paths.final_dir.exists()
    assert not paths.partial_dir.exists()
    assert (paths.final_dir / "media.mkv").read_bytes() == b"data"


def test_checksum_and_sidecar(tmp_path: Path) -> None:
    paths = item_paths(tmp_path, "youtube", "abc12345678")
    paths.final_dir.mkdir(parents=True)
    media = paths.final_dir / "media.mkv"
    media.write_bytes(b"hello")
    checksum = write_checksums(paths, media)
    assert checksum == sha256_file(media)
    assert paths.checksums_path.is_file()
    write_sidecar(paths, source={"id": "abc12345678"}, archive={"job_id": "j1"})
    assert paths.metadata_path.is_file()
