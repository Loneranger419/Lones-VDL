"""Channel avatar storage and selection helpers."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import FakeYtdlpAdapter

from lones_vdl.channel_avatars import (
    channel_url_from_source,
    ensure_channel_avatar,
    pick_avatar_url,
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
