"""API test fixtures: the real app, against real Postgres, Redis and a filesystem blob store."""

from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from origin_api.app import create_app
from origin_core.settings import BlobBackend, Settings

EXIFTOOL = os.environ.get("EXIFTOOL_PATH", "exiftool")


@pytest.fixture
def upload_limits() -> dict[str, int]:
    return {"ORIGIN_UPLOAD_MAX_BYTES": 20_000_000, "ORIGIN_UPLOAD_MAX_PIXELS": 50_000_000}


@pytest.fixture
async def app(
    database_url: str, redis_url: str, tmp_path: Path, upload_limits: dict[str, int]
) -> AsyncIterator[FastAPI]:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        ORIGIN_ENV="test",
        DATABASE_URL=database_url,
        REDIS_URL=redis_url,
        BLOB_BACKEND=BlobBackend.FILESYSTEM,
        BLOB_DIR=tmp_path / "blobs",
        EXIFTOOL_PATH=EXIFTOOL,
        **upload_limits,  # pyright: ignore[reportArgumentType]
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
def exiftool_available() -> bool:
    found = shutil.which(EXIFTOOL) is not None
    if not found and os.environ.get("ORIGIN_REQUIRE_SERVICES") == "1":
        pytest.fail(f"exiftool not found ({EXIFTOOL})")
    return found
