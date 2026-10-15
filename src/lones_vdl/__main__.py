"""CLI entry: run the API with uvicorn."""

import uvicorn

from lones_vdl.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "lones_vdl.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
