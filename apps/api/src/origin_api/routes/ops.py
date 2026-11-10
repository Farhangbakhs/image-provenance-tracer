"""Liveness and readiness."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from origin_api.schemas import DependencyCheck, Livez, Readyz
from origin_api.state import State
from origin_core import __version__

router = APIRouter(tags=["ops"])

CHECK_TIMEOUT_S = 3.0


async def _check(probe: Callable[[], Awaitable[object]]) -> DependencyCheck:
    started = time.monotonic()
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            await probe()
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return DependencyCheck(ok=False, latency_ms=elapsed, error=f"{type(exc).__name__}: {exc}")
    return DependencyCheck(ok=True, latency_ms=int((time.monotonic() - started) * 1000))


@router.get("/livez")
async def livez() -> Livez:
    """Process liveness: answers as long as the event loop runs."""
    return Livez(status="ok", version=__version__)


@router.get("/readyz", responses={503: {"model": Readyz}})
async def readyz(state: State, response: Response) -> Readyz:
    """Readiness: the database, Redis and object storage all answer."""

    async def database() -> None:
        async with state.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def redis() -> None:
        await state.redis.ping()  # pyright: ignore[reportUnknownMemberType]

    db_check, redis_check, storage_check = await asyncio.gather(
        _check(database), _check(redis), _check(state.blobs.ensure_ready)
    )
    checks = {"database": db_check, "redis": redis_check, "storage": storage_check}
    healthy = all(c.ok for c in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readyz(status="ok" if healthy else "degraded", version=__version__, checks=checks)
