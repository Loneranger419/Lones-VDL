"""The frontend's typed API client is generated from a committed copy of the schema."""

from __future__ import annotations

from pathlib import Path

from lones_vdl.cli import openapi_json

SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend/src/lib/api/openapi.json"


def test_frontend_schema_is_current():
    assert SNAPSHOT.read_text(encoding="utf-8") == openapi_json(), (
        "API changed: run `npm run api` in frontend/ (regenerates openapi.json + types)"
    )
