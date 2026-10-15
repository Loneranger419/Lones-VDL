"""FastAPI application factory (health only in Milestone 0)."""

from fastapi import FastAPI

from lones_vdl import __version__


def create_app() -> FastAPI:
    app = FastAPI(
        title="Lones-VDL",
        version=__version__,
        description="YouTube and Twitch video archival service",
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
