"""arq worker: executes pipeline runs. Start with `arq origin_worker.main.WorkerSettings`."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from arq.connections import RedisSettings
from redis.asyncio import Redis

from origin_core.db.session import make_engine, make_sessionmaker
from origin_core.logging import configure_logging
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.registry import default_stages
from origin_core.pipeline.runner import PipelineRunner
from origin_core.settings import get_settings

EXECUTE_RUN = "execute_run"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    engine = make_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    ctx["engine"] = engine
    ctx["redis"] = redis
    ctx["pipeline"] = PipelineRunner(
        sessions=make_sessionmaker(engine), events=RunEventBus(redis), stages=default_stages()
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["redis"].aclose()
    await ctx["engine"].dispose()


async def execute_run(ctx: dict[str, Any], run_id: str) -> str:
    pipeline: PipelineRunner = ctx["pipeline"]
    status = await pipeline.execute(uuid.UUID(run_id))
    return status.value


class WorkerSettings:
    functions: ClassVar[list[Any]] = [execute_run]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # A run is resumable, so a retry after a crash continues from the last finished stage.
    max_tries = 3
    job_timeout = 30 * 60
