"""Exporting the library's database state and installing it on another host."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from conftest import add_account, enqueue, wait_idle

from lones_vdl import cli
from lones_vdl.config import Settings, get_settings
from lones_vdl.services import state_transfer as transfer

IDS = ("okokokokok1", "okokokokok2")


@pytest.fixture
def source(authed):
    """A running install with a library, progress, a collection, and an account."""
    for vid in IDS:
        enqueue(authed, vid)
    wait_idle(authed)
    pks = [
        v["id"] for v in authed.get("/api/videos", params={"sort": "archived_asc"}).json()["items"]
    ]
    authed.put(f"/api/videos/{pks[0]}/progress", json={"position_seconds": 20})
    created = authed.post("/api/collections", json={"name": "Favourites"}).json()
    authed.post(f"/api/collections/{created['id']}/items", json={"video_ids": pks})
    add_account(authed)
    return authed


def rows(settings: Settings, sql: str) -> list[tuple]:
    conn = sqlite3.connect(settings.database_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def new_install(tmp_path: Path, name: str = "new") -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / name / "data", archive_root=tmp_path / "x")


def test_export_keeps_library_state_and_drops_local_state(source, settings, tmp_path):
    result = transfer.export_state(settings, tmp_path / "state.zip")
    assert result.counts == {
        "videos": 2,
        "channels": 1,
        "collections": 1,
        "creators": 0,
        "watch_progress": 1,
    }

    with zipfile.ZipFile(tmp_path / "state.zip") as bundle:
        assert sorted(bundle.namelist()) == ["manifest.json", "state.db"]
        manifest = json.loads(bundle.read("manifest.json"))
        bundle.extract("state.db", tmp_path / "out")
    assert manifest["includes_password"] is True
    conn = sqlite3.connect(tmp_path / "out" / "state.db")
    count = lambda table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: E731
    assert count("videos") == 2 and count("collection_items") == 2
    assert count("jobs") == 0 and count("accounts") == 0 and count("sessions") == 0
    assert count("access_attempts") == 0
    keys = {k for (k,) in conn.execute("SELECT key FROM app_settings")}
    assert "auth.password_hash" in keys
    assert not any(k.startswith("policy.") for k in keys)
    conn.close()
    assert not list(tmp_path.glob(".lvdl-export-*"))  # no scratch left behind


def test_export_can_leave_the_password_out(source, settings, tmp_path):
    transfer.export_state(settings, tmp_path / "state.zip", include_password=False)
    with zipfile.ZipFile(tmp_path / "state.zip") as bundle:
        assert json.loads(bundle.read("manifest.json"))["includes_password"] is False
        bundle.extract("state.db", tmp_path / "out")
    conn = sqlite3.connect(tmp_path / "out" / "state.db")
    assert conn.execute("SELECT COUNT(*) FROM app_settings WHERE key LIKE 'auth.%'").fetchone() == (
        0,
    )
    conn.close()


def test_import_into_a_fresh_install(source, settings, tmp_path):
    transfer.export_state(settings, tmp_path / "state.zip")
    fresh = new_install(tmp_path)

    manifest = transfer.import_state(fresh, tmp_path / "state.zip")

    assert manifest["counts"]["videos"] == 2
    assert rows(fresh, "SELECT COUNT(*) FROM videos") == [(2,)]
    assert rows(fresh, "SELECT position_seconds FROM watch_progress") == [(20.0,)]
    assert rows(fresh, "SELECT name FROM collections") == [("Favourites",)]
    assert rows(fresh, "SELECT COUNT(*) FROM accounts") == [(0,)]
    # The directory in the database is relative to the archive, so it works wherever that lives.
    assert all(not Path(d).is_absolute() for (d,) in rows(fresh, "SELECT directory FROM videos"))


def test_import_refuses_an_install_that_has_a_library(source, settings, tmp_path):
    transfer.export_state(settings, tmp_path / "state.zip")
    with pytest.raises(transfer.StateTransferError, match="--replace"):
        transfer.import_state(settings, tmp_path / "state.zip")
    # The refused import changed nothing.
    assert rows(settings, "SELECT COUNT(*) FROM videos") == [(2,)]


def test_replace_keeps_the_old_database(source, settings, tmp_path):
    transfer.export_state(settings, tmp_path / "state.zip")
    other = new_install(tmp_path, "other")
    transfer.import_state(other, tmp_path / "state.zip")
    # Give `other` its own library so there is something to replace.
    conn = sqlite3.connect(other.database_path)
    conn.execute(
        "INSERT INTO collections (name, created_at, updated_at) "
        "VALUES ('Mine', '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    transfer.import_state(other, tmp_path / "state.zip", replace=True)

    assert rows(other, "SELECT name FROM collections") == [("Favourites",)]
    [backup] = list(other.database_path.parent.glob("lones_vdl.db.before-import-*"))
    conn = sqlite3.connect(backup)
    assert conn.execute("SELECT COUNT(*) FROM collections").fetchone() == (2,)
    conn.close()


def test_bad_and_newer_bundles_are_rejected(source, settings, tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(transfer.StateTransferError, match="not a Lones-VDL"):
        transfer.import_state(new_install(tmp_path), junk)

    transfer.export_state(settings, tmp_path / "state.zip")
    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(tmp_path / "state.zip") as old, zipfile.ZipFile(newer, "w") as out:
        manifest = json.loads(old.read("manifest.json"))
        manifest["revision"] = "9999"
        out.writestr("manifest.json", json.dumps(manifest))
        out.writestr("state.db", old.read("state.db"))
    with pytest.raises(transfer.StateTransferError, match="newer version"):
        transfer.import_state(new_install(tmp_path), newer)


def test_cli_round_trip(source, settings, tmp_path, monkeypatch, capsys):
    bundle = tmp_path / "state.zip"
    monkeypatch.chdir(tmp_path)  # no stray .env
    monkeypatch.setenv("LONES_VDL_DATA_DIR", str(settings.data_dir))
    get_settings.cache_clear()
    assert cli.main(["state", "export", str(bundle)]) == 0
    assert "password hash" in capsys.readouterr().out

    monkeypatch.setenv("LONES_VDL_DATA_DIR", str(tmp_path / "elsewhere"))
    get_settings.cache_clear()
    assert cli.main(["state", "import", str(bundle)]) == 0
    assert "imported (2 videos" in capsys.readouterr().out
    assert cli.main(["state", "import", str(bundle)]) == 1  # now it has a library
    assert "--replace" in capsys.readouterr().err
    get_settings.cache_clear()
