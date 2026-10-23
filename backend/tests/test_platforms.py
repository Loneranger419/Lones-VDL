import pytest

from lones_vdl.platforms import UrlKind, parse_url

VID = "dQw4w9WgXcQ"
CHANNEL = "UC" + "a" * 22


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}&t=42s",
        f"https://m.youtube.com/watch?v={VID}",
        f"https://music.youtube.com/watch?v={VID}",
        f"https://youtu.be/{VID}?si=abc",
        f"youtu.be/{VID}",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/live/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube-nocookie.com/embed/{VID}",
        f"https://www.youtube.com/watch?v={VID}&list=PL1234567890",
    ],
)
def test_video_urls(url):
    parsed = parse_url(url)
    assert parsed is not None
    assert (parsed.platform, parsed.kind, parsed.id) == ("youtube", UrlKind.VIDEO, VID)
    assert parsed.url == f"https://www.youtube.com/watch?v={VID}"


def test_playlist_url():
    parsed = parse_url("https://www.youtube.com/playlist?list=PLabcdefghij12")
    assert parsed is not None and parsed.kind == UrlKind.PLAYLIST
    assert parsed.id == "PLabcdefghij12"


@pytest.mark.parametrize(
    ("url", "channel_id"),
    [
        ("https://www.youtube.com/@SomeCreator", None),
        ("https://www.youtube.com/@SomeCreator/videos", None),
        (f"https://www.youtube.com/channel/{CHANNEL}", CHANNEL),
        (f"https://www.youtube.com/channel/{CHANNEL}/streams", CHANNEL),
        ("https://www.youtube.com/c/legacyname", None),
    ],
)
def test_channel_urls(url, channel_id):
    parsed = parse_url(url)
    assert parsed is not None and parsed.kind == UrlKind.CHANNEL
    assert parsed.id == channel_id


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://vimeo.com/12345",
        "https://www.youtube.com/watch?v=short",
        "https://youtu.be/",
        "https://www.youtube.com/@creator/community",
        "https://evil-youtube.com/watch?v=dQw4w9WgXcQ",
        "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/feed/subscriptions",
    ],
)
def test_rejects(url):
    assert parse_url(url) is None
