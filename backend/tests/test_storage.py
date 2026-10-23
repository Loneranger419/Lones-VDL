import json

import pytest

from lones_vdl.storage import archive


def make_outputs(workdir):
    (workdir / "media.webm").write_bytes(b"media")
    (workdir / "media.f247.webm").write_bytes(b"fragment")
    (workdir / "media.webm.part").write_bytes(b"part")
    (workdir / "info.info.json").write_text("{}")
    (workdir / "resolved.json").write_text("{}")
    (workdir / "thumbnail.webp").write_bytes(b"w")
    (workdir / "thumbnail.jpg").write_bytes(b"j")
    (workdir / "subtitles").mkdir()
    (workdir / "subtitles" / "subs.en.vtt").write_text("WEBVTT")
    (workdir / "junk").mkdir()
    (workdir / "junk" / "x.tmp").write_text("x")


def test_discover_and_normalize(tmp_path):
    make_outputs(tmp_path)
    outputs = archive.discover_outputs(tmp_path)
    assert outputs.media.name == "media.webm"
    assert outputs.thumbnail.name == "thumbnail.jpg"
    final = archive.normalize(tmp_path, outputs, fallback_info=tmp_path / "resolved.json")
    names = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert names == ["info.json", "media.webm", "subtitles", "subtitles/en.vtt", "thumbnail.jpg"]
    assert final.subtitles == [tmp_path / "subtitles" / "en.vtt"]


def test_fallback_info_used_when_missing(tmp_path):
    (tmp_path / "media.mp4").write_bytes(b"m")
    (tmp_path / "resolved.json").write_text('{"id": "x"}')
    final = archive.normalize(
        tmp_path, archive.discover_outputs(tmp_path), fallback_info=tmp_path / "resolved.json"
    )
    assert final.info == tmp_path / "info.json"


def test_no_media_is_an_error(tmp_path):
    (tmp_path / "media.webm.part").write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        archive.discover_outputs(tmp_path)


def test_checksums_and_sidecar(tmp_path):
    (tmp_path / "media.webm").write_bytes(b"abc")
    archive.write_sidecar(tmp_path, {"video_id": "x"})
    sums = archive.write_checksums(tmp_path)
    assert sums["media.webm"] == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert "metadata.json" in sums and "checksums.json" not in sums
    assert json.loads((tmp_path / "metadata.json").read_text())["schema_version"] == 1


def test_promote_refuses_to_overwrite(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    dest = tmp_path / "youtube" / "abc"
    archive.promote(work, dest)
    assert dest.is_dir() and not work.exists()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(archive.ArchiveConflict):
        archive.promote(other, dest)


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 101, "a b"])
def test_video_dir_rejects_unsafe_ids(tmp_path, bad):
    with pytest.raises(ValueError):
        archive.video_dir(tmp_path, "youtube", bad)
