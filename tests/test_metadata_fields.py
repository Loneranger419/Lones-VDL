"""Unit tests for browse field extraction."""

from __future__ import annotations

from lones_vdl.metadata_fields import extract_browse_fields, parse_upload_date, sort_date_value


def test_extract_complete_fields() -> None:
    browse = extract_browse_fields(
        {
            "title": "Hello",
            "channel": "Example",
            "channel_id": "UCabc",
            "upload_date": "20240115",
            "webpage_url": "https://www.youtube.com/watch?v=abc",
        }
    )
    assert browse.incomplete is False
    assert browse.gaps == ()
    assert browse.channel_id == "UCabc"
    assert browse.upload_date == "20240115"


def test_extract_marks_gaps_and_synthesizes_channel_id() -> None:
    browse = extract_browse_fields({"title": "Only title", "uploader": "Someone"})
    assert browse.incomplete is True
    assert "upload_date" in browse.gaps
    assert browse.channel == "Someone"
    assert browse.channel_id == "name:someone"


def test_parse_upload_date_from_timestamp() -> None:
    assert parse_upload_date({"timestamp": 1_255_449_600}) == "20091013"


def test_sort_date_falls_back_to_archived_at() -> None:
    archived = "2024-06-01T12:00:00+00:00"
    assert sort_date_value(upload_date=None, archived_at=archived) == "20240601"
    assert sort_date_value(upload_date="20200101", archived_at=archived) == "20200101"
