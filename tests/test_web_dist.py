"""Built web UI path resolution for production/Docker."""

from __future__ import annotations

from pathlib import Path

from lones_vdl.config import Settings, resolve_web_dist


def test_resolve_web_dist_explicit(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    settings = Settings.model_validate({"web_dist": dist})
    assert resolve_web_dist(settings) == dist


def test_resolve_web_dist_missing_explicit(tmp_path: Path) -> None:
    settings = Settings.model_validate({"web_dist": tmp_path / "nope"})
    assert resolve_web_dist(settings) is None
