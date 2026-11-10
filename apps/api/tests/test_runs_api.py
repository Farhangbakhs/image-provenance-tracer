"""API against real Postgres and Redis: readiness, run status and the SSE relay."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from testkit import SeedRun

from origin_core.pipeline.events import EventType, RunEvent, RunEventBus

pytestmark = [pytest.mark.db, pytest.mark.redis]


def _sse(text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for block in text.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            fields[key] = value
        if fields:
            events.append(fields)
    return events


async def test_readyz_reports_each_dependency(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"database", "redis", "storage"}
    assert all(check["ok"] for check in body["checks"].values())


async def test_get_run(client: httpx.AsyncClient, seed_run: SeedRun) -> None:
    run_id = await seed_run()
    response = await client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["stage_order"] == ["ingest", "discover", "verify", "date", "branch", "report"]
    assert (await client.get(f"/runs/{uuid.uuid4()}")).status_code == 404


async def test_events_stream_until_terminal_and_resume(
    client: httpx.AsyncClient, redis: Redis, seed_run: SeedRun
) -> None:
    run_id = await seed_run()
    bus = RunEventBus(redis)
    first = await bus.publish(RunEvent(type=EventType.RUN_STARTED, run_id=run_id))
    await bus.publish(RunEvent(type=EventType.STAGE_STARTED, run_id=run_id, stage="ingest"))
    await bus.publish(RunEvent(type=EventType.RUN_SUCCEEDED, run_id=run_id))

    response = await client.get(f"/runs/{run_id}/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse(response.text)
    assert [e["event"] for e in events] == ["run.started", "stage.started", "run.succeeded"]
    assert json.loads(events[1]["data"])["stage"] == "ingest"
    assert events[0]["id"] == first

    resumed = await client.get(f"/runs/{run_id}/events", headers={"Last-Event-ID": first})
    assert [e["event"] for e in _sse(resumed.text)] == ["stage.started", "run.succeeded"]


async def test_finished_run_without_history_yields_stored_outcome(
    client: httpx.AsyncClient, seed_run: SeedRun, database_url: str
) -> None:
    from sqlalchemy import update

    from origin_core.db.models import Run
    from origin_core.db.session import make_engine, make_sessionmaker
    from origin_core.enums import RunStatus

    run_id = await seed_run()
    engine = make_engine(database_url)
    async with make_sessionmaker(engine).begin() as session:
        await session.execute(
            update(Run).where(Run.id == run_id).values(status=RunStatus.FAILED, error="boom")
        )
    await engine.dispose()

    events = _sse((await client.get(f"/runs/{run_id}/events")).text)
    assert [e["event"] for e in events] == ["run.failed"]
    assert json.loads(events[0]["data"])["detail"]["error"] == "boom"
