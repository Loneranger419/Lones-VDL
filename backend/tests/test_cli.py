import io
import sys

from lones_vdl import cli
from lones_vdl.config import get_settings

EXPORT = (
    "# Netscape HTTP Cookie File\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\ttopsecret\n"
    ".paypal.com\tTRUE\t/\tTRUE\t4102444800\tx\ty\n"
)


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("LONES_VDL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)  # no stray .env
    get_settings.cache_clear()


def test_cookies_import_from_file(monkeypatch, tmp_path, capsys):
    _env(monkeypatch, tmp_path)
    source = tmp_path / "export.txt"
    source.write_text(EXPORT)
    assert cli.main(["cookies", "import", str(source), "--delete-source"]) == 0
    stored = (tmp_path / "data" / "secrets" / "cookies.txt").read_text()
    assert "SID" in stored and "paypal" not in stored
    assert not source.exists()
    assert "topsecret" not in capsys.readouterr().out
    get_settings.cache_clear()


def test_cookies_import_from_stdin(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(EXPORT.encode())))
    assert cli.main(["cookies", "import", "-"]) == 0
    assert (tmp_path / "data" / "secrets" / "cookies.txt").is_file()
    get_settings.cache_clear()


def test_cookies_import_rejects_export_without_login(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    source = tmp_path / "export.txt"
    source.write_text(".youtube.com\tTRUE\t/\tTRUE\t4102444800\tPREF\tx\n")
    assert cli.main(["cookies", "import", str(source)]) == 1
    assert not (tmp_path / "data" / "secrets" / "cookies.txt").exists()
    get_settings.cache_clear()
