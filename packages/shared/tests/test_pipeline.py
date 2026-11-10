"""PipelineRunner: ordered, resumable, and recorded in runs.stages, audit log and events."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from origin_core.db.models import AuditEvent, Run
from origin_core.db.session import make_sessionmaker
from origin_core.enums import RunStatus
from origin_core.pipeline.events import EventType, RunEventBus
from origin_core.pipeline.registry import default_stages
from origin_core.pipeline.runner import PipelineRunner, RunNotFound, StageContext, StageResult

pytestmark = [pytest.mark.db, pytest.mark.redis]


class RecordingStage:
    def __init__(self, name: str, log: list[str], *, fail_times: int = 0) -> None:
        self.name: str = name
        self._log = log
        self._fail_times = fail_times

    async def run(self, ctx: StageContext) -> StageResult:
        self._log.append(self.name)
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError(f"{self.name} broke")
        await ctx.progress(self.name, done=1)
        return StageResult(counts={"items": len(self.name)})


def _runner(engine: AsyncEngine, redis: Redis, stages: list[RecordingStage]) -> PipelineRunner:
    return PipelineRunner(
        sessions=make_sessionmaker(engine), events=RunEventBus(redis), stages=stages
    )


async def _events(redis: Redis, run_id: uuid.UUID) -> list[tuple[EventType, str | None]]:
    batch = await RunEventBus(redis).read(run_id, block_ms=None, count=1000)
    return [(event.type, event.stage) for _, event in batch]


async def test_empty_pipeline_completes(
    db_engine: AsyncEngine, redis: Redis, seed_run: Callable[[], object]
) -> None:
    run_id = await seed_run()  # type: ignore[misc]
    assert isinstance(run_id, uuid.UUID)
    status = await PipelineRunner(
        sessions=make_sessionmaker(db_engine), events=RunEventBus(redis), stages=default_stages()
    ).execute(run_id)

    assert status is RunStatus.SUCCEEDED
    assert await _events(redis, run_id) == [
        (EventType.RUN_STARTED, None),
        (EventType.RUN_SUCCEEDED, None),
    ]
    async with make_sessionmaker(db_engine)() as session:
        run = await session.get_one(Run, run_id)
    assert run.started_at is not None and run.finished_at is not None


async def test_stages_run_in_order_and_are_recorded(
    db_engine: AsyncEngine, redis: Redis, seed_run: Callable[[], object]
) -> None:
    run_id = await seed_run()  # type: ignore[misc]
    assert isinstance(run_id, uuid.UUID)
    log: list[str] = []
    status = await _runner(
        db_engine, redis, [RecordingStage("ingest", log), RecordingStage("discover", log)]
    ).execute(run_id)

    assert status is RunStatus.SUCCEEDED
    assert log == ["ingest", "discover"]
    async with make_sessionmaker(db_engine)() as session:
        run = await session.get_one(Run, run_id)
        actions = (
            (
                await session.execute(
                    select(AuditEvent.action)
                    .where(AuditEvent.run_id == run_id)
                    .order_by(AuditEvent.id)
                )
            )
            .scalars()
            .all()
        )
    assert run.stages["ingest"]["status"] == "succeeded"
    assert run.stages["discover"]["counts"] == {"items": 8}
    assert actions == [
        "run.started",
        "stage.running",
        "stage.succeeded",
        "stage.running",
        "stage.succeeded",
        "run.succeeded",
    ]
    types = [t for t, _ in await _events(redis, run_id)]
    assert types.count(EventType.STAGE_PROGRESS) == 2
    assert types[-1] is EventType.RUN_SUCCEEDED


async def test_failure_stops_the_run_and_retry_resumes(
    db_engine: AsyncEngine, redis: Redis, seed_run: Callable[[], object]
) -> None:
    run_id = await seed_run()  # type: ignore[misc]
    assert isinstance(run_id, uuid.UUID)
    log: list[str] = []
    stages = [
        RecordingStage("ingest", log),
        RecordingStage("discover", log, fail_times=1),
        RecordingStage("verify", log),
    ]
    runner = _runner(db_engine, redis, stages)

    assert await runner.execute(run_id) is RunStatus.FAILED
    async with make_sessionmaker(db_engine)() as session:
        run = await session.get_one(Run, run_id)
    assert run.status is RunStatus.FAILED
    assert run.error == "stage discover failed: RuntimeError: discover broke"
    assert "verify" not in run.stages

    # The retry skips the finished stage and continues from the failed one.
    assert await runner.execute(run_id) is RunStatus.SUCCEEDED
    assert log == ["ingest", "discover", "discover", "verify"]
    assert (EventType.STAGE_SKIPPED, "ingest") in await _events(redis, run_id)


async def test_succeeded_run_is_not_executed_again(
    db_engine: AsyncEngine, redis: Redis, seed_run: Callable[[], object]
) -> None:
    run_id = await seed_run()  # type: ignore[misc]
    assert isinstance(run_id, uuid.UUID)
    log: list[str] = []
    runner = _runner(db_engine, redis, [RecordingStage("ingest", log)])
    await runner.execute(run_id)
    await runner.execute(run_id)
    assert log == ["ingest"]


async def test_unknown_run_raises(db_engine: AsyncEngine, redis: Redis) -> None:
    with pytest.raises(RunNotFound):
        await _runner(db_engine, redis, []).execute(uuid.uuid4())


def test_duplicate_stage_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        PipelineRunner(
            sessions=None,  # pyright: ignore[reportArgumentType]
            events=None,  # pyright: ignore[reportArgumentType]
            stages=[RecordingStage("a", []), RecordingStage("a", [])],
        )
