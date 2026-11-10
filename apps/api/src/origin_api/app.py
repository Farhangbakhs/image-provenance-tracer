"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from origin_core import __version__
from origin_core.logging import configure_logging
from origin_core.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    app = FastAPI(title="ORIGIN API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    @app.get("/livez", tags=["ops"])
    async def livez() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        """Process liveness: answers as long as the event loop runs."""
        return {"status": "ok", "version": __version__}

    return app
