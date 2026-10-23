from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lones_vdl import __version__
from lones_vdl.config import Settings
from lones_vdl.main import create_app


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "build"
    (root / "_app" / "immutable").mkdir(parents=True)
    (root / "index.html").write_text("<html>spa</html>")
    (root / "favicon.png").write_bytes(b"png")
    (root / "manifest.webmanifest").write_text("{}")
    (root / "_app" / "immutable" / "app.abc123.js").write_text("js")
    (tmp_path / "secret.txt").write_text("outside")
    return root


def client_for(tmp_path: Path, dist: Path | None) -> TestClient:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        archive_root=tmp_path / "archive",
        frontend_dist=dist if dist is not None else tmp_path / "missing",
    )
    return TestClient(create_app(settings))


def test_health(tmp_path):
    response = client_for(tmp_path, None).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_spa_serves_files_and_falls_back_to_index(tmp_path, dist):
    client = client_for(tmp_path, dist)
    assert client.get("/favicon.png").content == b"png"
    for route in ("/", "/library", "/watch/abc123"):
        response = client.get(route)
        assert response.text == "<html>spa</html>"
        assert response.headers["cache-control"] == "no-cache"


def test_spa_caches_immutable_assets(tmp_path, dist):
    response = client_for(tmp_path, dist).get("/_app/immutable/app.abc123.js")
    assert "immutable" in response.headers["cache-control"]


def test_spa_revalidates_other_files_and_types_the_manifest(tmp_path, dist):
    client = client_for(tmp_path, dist)
    assert client.get("/favicon.png").headers["cache-control"] == "no-cache"
    manifest = client.get("/manifest.webmanifest")
    assert manifest.headers["content-type"].startswith("application/manifest+json")


def test_unknown_api_route_is_404_not_index(tmp_path, dist):
    client = client_for(tmp_path, dist)
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api").status_code == 404


def test_spa_does_not_escape_dist(tmp_path, dist):
    response = client_for(tmp_path, dist).get("/..%2Fsecret.txt")
    assert response.text != "outside"


def test_api_only_without_frontend(tmp_path):
    client = client_for(tmp_path, None)
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200


def test_derived_paths_live_under_data_dir(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    for path in (
        settings.database_path,
        settings.cookies_file,
        settings.ytdlp_dir,
        settings.job_logs_dir,
    ):
        assert path.is_relative_to(tmp_path)
