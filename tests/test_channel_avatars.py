"""Channel avatar storage and selection helpers."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import FakeYtdlpAdapter

from lones_vdl.channel_avatars import (
    channel_url_from_source,
    ensure_channel_avatar,
    pick_avatar_url,
    twitch_login_from_url,
)
from lones_vdl.storage import CHANNELS_DIR_NAME, sanitize_channel_dir_name


def test_pick_avatar_prefers_avatar_id() -> None:
    url = pick_avatar_url(
        {
            "thumbnails": [
                {"id": "banner", "url": "https://example.test/banner.jpg"},
                {"id": "avatar_uncropped", "url": "https://example.test/avatar.jpg"},
            ]
        }
    )
    assert url == "https://example.test/avatar.jpg"


def test_twitch_channel_url_from_webpage_and_login() -> None:
    assert (
        channel_url_from_source(
            {
                "webpage_url": (
                    "https://www.twitch.tv/katrine/clip/PlacidDifferentWolverineThisIsSparta-x"
                )
            }
        )
        == "https://www.twitch.tv/katrine"
    )
    assert channel_url_from_source({"uploader_id": "veronika"}) == "https://www.twitch.tv/veronika"
    assert twitch_login_from_url("https://www.twitch.tv/videos/123") is None


def test_sanitize_channel_dir_allows_windows() -> None:
    assert ":" not in sanitize_channel_dir_name("name:someone")
    assert sanitize_channel_dir_name("UC_abc") == "UC_abc"


def test_ensure_writes_avatar_under_channels(tmp_path: Path) -> None:
    adapter = FakeYtdlpAdapter()
    path = ensure_channel_avatar(
        archive_root=tmp_path,
        platform="youtube",
        channel_id="UC_test_channel",
        channel_url="https://www.youtube.com/channel/UC_test_channel",
        adapter=adapter,
    )
    assert path is not None
    assert path.is_file()
    assert CHANNELS_DIR_NAME in path.parts
    assert channel_url_from_source({"channel_url": "https://c.example"}) == "https://c.example"
    again = ensure_channel_avatar(
        archive_root=tmp_path,
        platform="youtube",
        channel_id="UC_test_channel",
        channel_url="https://www.youtube.com/channel/UC_test_channel",
        adapter=adapter,
    )
    assert again == path


def test_ensure_twitch_uses_profile_fetch(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from lones_vdl import channel_avatars as ca

    monkeypatch.setattr(
        ca,
        "fetch_twitch_profile_image_url",
        lambda **_kwargs: "https://example.test/profile.png",
    )

    class CapturingAdapter(FakeYtdlpAdapter):
        def download_channel_avatar(self, channel_url: str, *, dest_dir: Path) -> Path | None:
            raise AssertionError("yt-dlp avatar path should not be needed for Twitch")

    def fake_download(url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"twitch-avatar")
        return dest

    monkeypatch.setattr(ca, "_download_image", fake_download)
    path = ensure_channel_avatar(
        archive_root=tmp_path,
        platform="twitch",
        channel_id="41969829",
        channel_url="https://www.twitch.tv/katrine",
        adapter=CapturingAdapter(),
    )
    assert path is not None
    assert path.read_bytes() == b"twitch-avatar"
    assert "twitch" in path.parts
    assert CHANNELS_DIR_NAME in path.parts
