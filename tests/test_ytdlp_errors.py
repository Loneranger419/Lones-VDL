"""yt-dlp stderr summarization and classification."""

from __future__ import annotations

from lones_vdl.errors import TransientDownloadError
from lones_vdl.platform.ytdlp import (
    _classify_ytdlp_error,
    _subtitle_only_failure,
    summarize_ytdlp_output,
)


def test_summarize_prefers_error_lines() -> None:
    stderr = (
        "WARNING: The extractor specified to use impersonation for this download\n"
        "WARNING: again\n"
        "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests\n"
    )
    summary = summarize_ytdlp_output(stderr)
    assert summary.startswith("ERROR:")
    assert "429" in summary
    assert "WARNING" not in summary


def test_subtitle_only_failure_detection() -> None:
    assert _subtitle_only_failure(
        "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
    )
    assert not _subtitle_only_failure(
        "ERROR: Unable to download video subtitles for 'en': HTTP Error 429\n"
        "ERROR: video unavailable"
    )


def test_429_classified_transient_with_short_message() -> None:
    stderr = (
        "WARNING: impersonation noise\n" * 5
        + "ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests\n"
    )
    exc = _classify_ytdlp_error(stderr, 1)
    assert isinstance(exc, TransientDownloadError)
    assert "WARNING" not in str(exc)
    assert "429" in str(exc)
