"""Moving the library's database state to another install (export / import).

The archive folder is the portable source of truth for the videos themselves. This carries
what only the database knows: watch progress, collections, creators, channels and their
auto-archive settings, ignored videos, and runtime settings. A bundle is a zip with a
``manifest.json`` and a scrubbed copy of the database.

Left out on purpose: accounts and their cookies (re-export fresh ones on the new host), the job
queue and history, download-policy counters and any rate-limit pause, and login sessions.
The bundle does hold the admin password hash unless ``include_password`` is false, so treat it
as private.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError

from lones_vdl import __version__
from lones_vdl.config import Settings
from lones_vdl.db.migrate import SCRIPT_LOCATION

BUNDLE_FORMAT = "lones-vdl-state"
BUNDLE_VERSION = 1
DB_NAME = "state.db"
MANIFEST_NAME = "manifest.json"

# Tables whose rows belong to this install only.
_LOCAL_TABLES = ("access_attempts", "jobs", "accounts", "sessions")
_LOCAL_SETTINGS = ("policy.%", "cookies.health", "ytdlp.%")
_PASSWORD_KEY = "auth.password_hash"
# What counts as "this install already has a library" when importing.
_CONTENT_TABLES = ("videos", "channels", "collections", "creators")


class StateTransferError(Exception):
    pass


@dataclass(frozen=True)
class ExportResult:
    path: Path
    revision: str
    counts: dict[str, int]


def _script_directory() -> ScriptDirectory:
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    return ScriptDirectory.from_config(config)


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608


def _revision(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None:
        raise StateTransferError("the database has no migration version")
    return str(row[0])


def export_state(settings: Settings, out: Path, *, include_password: bool = True) -> ExportResult:
    """Write a bundle of the current database state. Safe while the app is running."""
    source_path = settings.database_path
    if not source_path.exists():
        raise StateTransferError(f"no database at {source_path}")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".lvdl-export-") as tmp:
        copy_path = Path(tmp) / DB_NAME
        source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True, timeout=30)
        copy = sqlite3.connect(copy_path)
        try:
            source.backup(copy)  # a consistent snapshot, even with the app writing
            for table in _LOCAL_TABLES:
                copy.execute(f"DELETE FROM {table}")  # noqa: S608
            for pattern in _LOCAL_SETTINGS:
                copy.execute("DELETE FROM app_settings WHERE key LIKE ?", (pattern,))
            if not include_password:
                copy.execute("DELETE FROM app_settings WHERE key = ?", (_PASSWORD_KEY,))
            copy.commit()
            revision = _revision(copy)
            counts = {name: _count(copy, name) for name in _CONTENT_TABLES}
            counts["watch_progress"] = _count(copy, "watch_progress")
            copy.execute("VACUUM")
        finally:
            copy.close()
            source.close()

        manifest = {
            "format": BUNDLE_FORMAT,
            "version": BUNDLE_VERSION,
            "app_version": __version__,
            "revision": revision,
            "created_at": datetime.now(UTC).isoformat(),
            "includes_password": include_password,
            "counts": counts,
        }
        partial = Path(tmp) / "bundle.zip"
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
            bundle.write(copy_path, DB_NAME)
        if os.name == "posix":
            partial.chmod(0o600)
        os.replace(partial, out)
    return ExportResult(path=out, revision=revision, counts=counts)


def read_manifest(bundle_path: Path) -> dict:
    try:
        with zipfile.ZipFile(bundle_path) as bundle:
            manifest = json.loads(bundle.read(MANIFEST_NAME))
            if DB_NAME not in bundle.namelist():
                raise StateTransferError("the bundle has no database")
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise StateTransferError(f"not a Lones-VDL state bundle: {exc}") from exc
    if manifest.get("format") != BUNDLE_FORMAT or manifest.get("version") != BUNDLE_VERSION:
        raise StateTransferError("not a Lones-VDL state bundle this version understands")
    return manifest


def existing_content(settings: Settings) -> dict[str, int]:
    """Row counts of what this install already has; empty if there is no library yet."""
    path = settings.database_path
    if not path.exists():
        return {}
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        counts = {}
        for table in _CONTENT_TABLES:
            try:
                counts[table] = _count(conn, table)
            except sqlite3.OperationalError:
                counts[table] = 0  # tables not created yet
        return {k: v for k, v in counts.items() if v}
    finally:
        conn.close()


def import_state(settings: Settings, bundle_path: Path, *, replace: bool = False) -> dict:
    """Install a bundle as this install's database. The app must not be running.

    Refuses to touch an install that already has a library unless ``replace`` is set; the old
    database is then kept next to the new one as ``lones_vdl.db.before-import-<time>``."""
    manifest = read_manifest(bundle_path)
    try:
        _script_directory().get_revision(manifest["revision"])
    except (CommandError, KeyError) as exc:
        raise StateTransferError(
            f"the bundle is from a newer version (database revision {manifest.get('revision')}); "
            "update this install first"
        ) from exc

    present = existing_content(settings)
    if present and not replace:
        found = ", ".join(f"{n} {k}" for k, n in present.items())
        raise StateTransferError(
            f"this install already has data ({found}); use --replace to overwrite it"
        )

    target = settings.database_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".lvdl-import-") as tmp:
        staged = Path(tmp) / DB_NAME
        with zipfile.ZipFile(bundle_path) as bundle, bundle.open(DB_NAME) as src:
            with staged.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        check = sqlite3.connect(staged)
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise StateTransferError(f"the bundle's database is damaged: {result}")
        finally:
            check.close()

        if target.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            backup = target.with_name(f"{target.name}.before-import-{stamp}")
            os.replace(target, backup)
        for suffix in ("-wal", "-shm"):
            target.with_name(target.name + suffix).unlink(missing_ok=True)
        os.replace(staged, target)
    return manifest
