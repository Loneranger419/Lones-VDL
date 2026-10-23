"""Tests for scripts/cookie_filter.py (moves into the v2 backend in Phase 1)."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cookie_filter as cf  # noqa: E402

NOW = 1_800_000_000  # 2027-01-15
FUTURE = 1_810_000_000
PAST = 1_700_000_000


def row(domain, name, value="secret-value", expires=FUTURE, *, http_only=False):
    prefix = "#HttpOnly_" if http_only else ""
    return f"{prefix}{domain}\tTRUE\t/\tTRUE\t{expires}\t{name}\t{value}"


def export(*rows: str) -> str:
    return "# Netscape HTTP Cookie File\r\n\r\n" + "\r\n".join(rows) + "\r\n"


def names(cookies):
    return sorted(c.name for c in cookies)


def test_httponly_rows_are_cookies_not_comments():
    text = export(row(".youtube.com", "SID", http_only=True), "# a real comment")
    cookies, summary = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert names(cookies) == ["SID"]
    assert cookies[0].http_only
    assert cf.serialize(cookies).splitlines()[-1].startswith("#HttpOnly_.youtube.com\t")
    assert summary.rows_read == 1


def test_keeps_only_platform_domains_on_dot_boundary():
    text = export(
        row(".youtube.com", "SID"),
        row("accounts.google.com", "LSID"),
        row(".paypal.com", "session"),
        row(".evilyoutube.com", "trap"),
        row(".twitch.tv", "auth-token"),
    )
    cookies, summary = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert names(cookies) == ["SID"]
    assert summary.dropped_domain == 4

    cookies, _ = cf.filter_cookies(text, ["youtube", "twitch"], now=NOW)
    assert names(cookies) == ["SID", "auth-token"]


def test_auth_summary_reports_earliest_expiry_across_domains():
    text = export(
        row(".youtube.com", "SID", expires=FUTURE + 500),
        row("m.youtube.com", "SID", expires=FUTURE),
    )
    _, summary = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert summary.auth_cookies["youtube"]["SID"] == cf._iso_date(FUTURE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 0),
        (1_808_270_465, 1_808_270_465),  # Unix seconds untouched
        (1_808_270_465_123, 1_808_270_465),  # Unix milliseconds
        (13_452_744_065_676_922, 1_808_270_465),  # WebKit µs since 1601
    ],
)
def test_normalize_expiry(raw, expected):
    assert cf.normalize_expiry(raw) == expected


def test_webkit_expiry_is_normalized_in_output():
    text = export(row(".youtube.com", "SID", expires=13_452_744_065_676_922))
    cookies, summary = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert cookies[0].expires == 1_808_270_465
    assert summary.expiry_normalized == 1
    assert summary.auth_cookies["youtube"]["SID"] == "2027-04-21"


def test_drops_expired_but_keeps_session_cookies():
    text = export(
        row(".youtube.com", "OLD", expires=PAST),
        row(".youtube.com", "SESSION", expires=0),
        row(".youtube.com", "SID"),
    )
    cookies, summary = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert names(cookies) == ["SESSION", "SID"]
    assert summary.dropped_expired == 1

    cookies, _ = cf.filter_cookies(text, ["youtube"], now=NOW, drop_expired=False)
    assert "OLD" in names(cookies)


def test_duplicates_keep_latest_expiry():
    text = export(
        row(".youtube.com", "SID", value="older", expires=FUTURE),
        row(".youtube.com", "SID", value="newer", expires=FUTURE + 100),
    )
    cookies, summary = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert [c.value for c in cookies] == ["newer"]
    assert summary.dropped_duplicate == 1


def test_malformed_rows_counted_and_skipped():
    text = export(
        "garbage line",
        ".youtube.com\tTRUE\t/\tTRUE\tnot-a-number\tX\tv",
        row(".youtube.com", "SID"),
    )
    cookies, summary = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert names(cookies) == ["SID"]
    assert summary.rows_malformed == 2


def test_values_containing_tabs_round_trip():
    text = export(row(".youtube.com", "SID", value="a\tb"))
    cookies, _ = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert cookies[0].value == "a\tb"
    again, _ = cf.filter_cookies(cf.serialize(cookies), ["youtube"], now=NOW)
    assert again == cookies


def test_warns_without_login_cookies():
    _, summary = cf.filter_cookies(export(row(".youtube.com", "PREF")), ["youtube"], now=NOW)
    assert any("login cookies" in w for w in summary.warnings)


def test_unknown_platform_rejected():
    with pytest.raises(ValueError):
        cf.filter_cookies(export(), ["vimeo"], now=NOW)


def test_summary_never_contains_values():
    text = export(row(".youtube.com", "SID", value="TOPSECRET", http_only=True))
    _, summary = cf.filter_cookies(text, ["youtube"], now=NOW)
    assert "TOPSECRET" not in json.dumps(asdict(summary))


def test_cli_writes_output_and_never_prints_values(tmp_path, capsys):
    src = tmp_path / "cookies.txt"
    src.write_text(export(row(".youtube.com", "SID", value="TOPSECRET"), row(".paypal.com", "p")))
    out = tmp_path / "filtered.txt"
    assert cf.main([str(src), "-o", str(out)]) == 0
    captured = capsys.readouterr()
    assert "TOPSECRET" not in captured.out + captured.err
    content = out.read_text()
    assert "TOPSECRET" in content and "paypal" not in content
    assert "\r" not in content


def test_cli_replace_refuses_to_write_empty_jar(tmp_path):
    src = tmp_path / "cookies.txt"
    original = export(row(".paypal.com", "p"))
    src.write_bytes(original.encode())
    assert cf.main([str(src), "--replace"]) == 1
    assert src.read_bytes() == original.encode()
