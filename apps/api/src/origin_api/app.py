"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from origin_api.routes import assets, cases, ops, runs, sightings
from origin_api.state import lifespan_for
from origin_core import __version__
from origin_core.logging import configure_logging
from origin_core.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    app = FastAPI(title="ORIGIN API", version=__version__, lifespan=lifespan_for(settings))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
        expose_headers=["Last-Event-ID"],
    )
    app.include_router(ops.router)
    app.include_router(cases.router)
    app.include_router(assets.router)
    app.include_router(runs.router)
    app.include_router(sightings.router)
    return app
