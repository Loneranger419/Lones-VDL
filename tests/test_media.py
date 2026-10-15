"""Unit tests for playback planning and remux helpers."""

from pathlib import Path

from lones_vdl.media import (
    ProbeResult,
    StreamInfo,
    ensure_playable_derivative,
    plan_playback,
)
from lones_vdl.storage import item_paths


class FakeMediaProcessor:
    def probe(self, path: Path) -> ProbeResult:
        return ProbeResult(
            format_name="matroska,webm",
            streams=[
                StreamInfo(codec_type="video", codec_name="av1"),
                StreamInfo(codec_type="audio", codec_name="opus"),
            ],
        )

    def remux_copy(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-derivative")


def test_plan_av1_opus_remuxes_to_webm() -> None:
    plan = plan_playback(
        ProbeResult(
            format_name="matroska,webm",
            streams=[
                StreamInfo("video", "av1"),
                StreamInfo("audio", "opus"),
            ],
        ),
        source_path=Path("media.mkv"),
    )
    assert plan.mode == "remux"
    assert plan.container == "webm"
    assert plan.derivative_relpath == "derivatives/play.webm"


def test_plan_h264_aac_mp4_original() -> None:
    plan = plan_playback(
        ProbeResult(
            format_name="mov,mp4,m4a",
            streams=[
                StreamInfo("video", "h264"),
                StreamInfo("audio", "aac"),
            ],
        ),
        source_path=Path("media.mp4"),
    )
    assert plan.mode == "original"
    assert plan.container == "mp4"


def test_plan_unavailable_without_reencode() -> None:
    plan = plan_playback(
        ProbeResult(
            format_name="matroska",
            streams=[
                StreamInfo("video", "hevc"),
                StreamInfo("audio", "flac"),
            ],
        )
    )
    assert plan.mode == "unavailable"


def test_ensure_playable_creates_derivative(tmp_path: Path) -> None:
    paths = item_paths(tmp_path, "youtube", "abc12345678")
    paths.final_dir.mkdir(parents=True)
    media = paths.final_dir / "media.mkv"
    media.write_bytes(b"original")
    plan = ensure_playable_derivative(
        paths=paths,
        media_file=media,
        processor=FakeMediaProcessor(),
    )
    assert plan.mode == "remux"
    assert (paths.final_dir / "derivatives" / "play.webm").read_bytes() == b"fake-derivative"


def test_remux_temp_keeps_container_extension() -> None:
    """Regression: .webm.partial broke ffmpeg muxer detection."""
    destination = Path("derivatives/play.webm")
    tmp = destination.with_name(f"{destination.stem}.partial{destination.suffix}")
    assert tmp.name == "play.partial.webm"
    assert tmp.suffix == ".webm"
