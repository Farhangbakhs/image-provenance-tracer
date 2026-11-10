"""The arq job wires settings, database, Redis and the pipeline together."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import SeedRun

from origin_core.pipeline.events import EventType, RunEventBus
from origin_core.settings import get_settings
from origin_worker.main import execute_run, shutdown, startup

pytestmark = [pytest.mark.db, pytest.mark.redis]


async def test_execute_run_job(
    monkeypatch: pytest.MonkeyPatch, database_url: str, redis_url: str, seed_run: SeedRun
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", redis_url)
    get_settings.cache_clear()
    ctx: dict[str, Any] = {}
    await startup(ctx)
    try:
        run_id = await seed_run()
        assert await execute_run(ctx, str(run_id)) == "succeeded"
        events = await RunEventBus(ctx["redis"]).read(run_id, block_ms=None)
        assert events[-1][1].type is EventType.RUN_SUCCEEDED
    finally:
        await shutdown(ctx)
        get_settings.cache_clear()
