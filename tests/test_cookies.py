"""Unit tests for Netscape cookie filtering."""

from pathlib import Path

import pytest

from lones_vdl.cookies import domain_allowed, filter_netscape_cookies

SAMPLE = """\
# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	0	VISITOR_INFO1_LIVE	yt-value
.google.com	TRUE	/	FALSE	0	SID	google-auth
.chatgpt.com	TRUE	/	FALSE	0	session	drop-me
.twitch.tv	TRUE	/	FALSE	0	auth-token	twitch-value
.github.com	TRUE	/	FALSE	0	user_session	drop-me-too
"""


def test_domain_allowed_suffix() -> None:
    assert domain_allowed(".www.youtube.com", {"youtube.com"})
    assert domain_allowed("youtube.com", {"youtube.com"})
    assert not domain_allowed("notyoutube.com", {"youtube.com"})


def test_filter_youtube_only(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    result = filter_netscape_cookies(path, platforms=["youtube"], write_backup=True)
    assert result.cookies_before == 5
    assert result.cookies_after == 2
    assert result.cookies_removed == 3
    assert (tmp_path / "cookies.txt.bak").is_file()
    text = path.read_text(encoding="utf-8")
    assert "youtube.com" in text
    assert "google.com" in text
    assert "chatgpt.com" not in text
    assert "twitch.tv" not in text
    assert "github.com" not in text


def test_filter_youtube_and_twitch(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    result = filter_netscape_cookies(path, platforms=["youtube", "twitch"], write_backup=False)
    assert result.cookies_after == 3
    text = path.read_text(encoding="utf-8")
    assert "twitch.tv" in text
    assert "chatgpt.com" not in text


def test_unknown_platform_rejected(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown"):
        filter_netscape_cookies(path, platforms=["vimeo"])
