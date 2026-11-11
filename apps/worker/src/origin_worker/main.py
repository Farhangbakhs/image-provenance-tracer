"""arq worker: executes pipeline runs. Start with `arq origin_worker.main.WorkerSettings`."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import httpx
from arq import func
from arq.connections import RedisSettings
from redis.asyncio import Redis

from origin_core.db.session import make_engine, make_sessionmaker
from origin_core.fetch import Fetcher
from origin_core.llm.registry import build_llm
from origin_core.llm.runner import LLMRunner
from origin_core.logging import configure_logging
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.jobs import EXECUTE_RUN
from origin_core.pipeline.runner import PipelineRunner
from origin_core.providers.fixtures import FixtureStore
from origin_core.providers.quota import DEFAULT_POLICIES
from origin_core.providers.registry import build_providers
from origin_core.providers.runner import ProviderRunner
from origin_core.settings import Environment, get_settings
from origin_core.storage import make_blob_store
from origin_worker.embedding import SSCDEmbedder, ensure_weights
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.stages import TelegramServices, TraceServices, build_stages
from origin_worker.telegram.collector import Collector, SSCDModel
from origin_worker.telegram.sources import Pacer, PreviewSource


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    engine = make_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    blobs = make_blob_store(settings)
    await blobs.ensure_ready()
    # Downloads the SSCD weights on first start (99 MB), then verifies them on every start.
    embedder = SSCDEmbedder(await ensure_weights(settings.models_dir))
    sessions = make_sessionmaker(engine)
    providers = build_providers(settings, sessions)
    http = httpx.AsyncClient()
    fetcher = Fetcher()
    runner = ProviderRunner(
        sessions=sessions,
        blobs=blobs,
        http=http,
        policies=DEFAULT_POLICIES,
        mode=settings.provider_mode,
        fixtures=FixtureStore((settings.fixtures_dir, settings.synthetic_fixtures_dir)),
        redact_secrets=providers.secrets,
    )
    llm = build_llm(settings)
    llm_runner = LLMRunner(
        sessions=sessions,
        blobs=blobs,
        http=http,
        mode=settings.provider_mode,
        fixtures=FixtureStore((settings.fixtures_dir, settings.synthetic_fixtures_dir)),
        redact_secrets=llm.secrets,
    )
    trace = TraceServices(
        providers=providers,
        runner=runner,
        fetcher=fetcher,
        thresholds=load_thresholds(),
        max_pixels=settings.upload_max_pixels,
        exiftool=settings.exiftool_path,
        llm=llm,
        llm_runner=llm_runner,
        telegram=TelegramServices(
            collector=Collector(
                sessions=sessions,
                blobs=blobs,
                embedder=SSCDModel(embedder),
                max_pixels=settings.upload_max_pixels,
                max_bytes=settings.upload_max_bytes,
            ),
            source=PreviewSource(fetcher, Pacer(settings.telegram_interval_s)),
        )
        # Demo mode never contacts Telegram; its Telegram case is seeded offline.
        if settings.enable_telegram and settings.env is not Environment.DEMO
        else None,
    )
    ctx["engine"] = engine
    ctx["redis"] = redis
    ctx["http"] = http
    ctx["fetcher"] = fetcher
    ctx["pipeline"] = PipelineRunner(
        sessions=sessions,
        events=RunEventBus(redis),
        stages=build_stages(blobs=blobs, embedder=embedder, trace=trace),
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["fetcher"].aclose()
    await ctx["http"].aclose()
    await ctx["redis"].aclose()
    await ctx["engine"].dispose()


async def execute_run(ctx: dict[str, Any], run_id: str) -> str:
    pipeline: PipelineRunner = ctx["pipeline"]
    status = await pipeline.execute(uuid.UUID(run_id))
    return status.value


class WorkerSettings:
    functions: ClassVar[list[Any]] = [func(execute_run, name=EXECUTE_RUN)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # A run is resumable, so a retry after a crash continues from the last finished stage.
    max_tries = 3
    job_timeout = 30 * 60
    # Refresh the heartbeat key (arq:queue:health-check) often, so a hung worker shows up
    # unhealthy within a minute instead of an hour (arq's default).
    health_check_interval = 30
