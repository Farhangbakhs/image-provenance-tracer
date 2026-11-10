"""Run status and live progress (server-sent events relayed from the run's event stream)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from origin_api.schemas import RunOut
from origin_api.state import Session, State
from origin_core.db.models import Run
from origin_core.enums import RunStatus
from origin_core.pipeline.events import TERMINAL, EventType, RunEvent
from origin_core.pipeline.registry import STAGE_ORDER

router = APIRouter(prefix="/runs", tags=["runs"])

KEEPALIVE_MS = 15_000


async def run_or_404(run_id: uuid.UUID, session: Session) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


RunRow = Annotated[Run, Depends(run_or_404)]


@router.get("/{run_id}")
async def get_run(run: RunRow) -> RunOut:
    return RunOut.from_row(run, list(STAGE_ORDER))


@router.get("/{run_id}/events", response_class=EventSourceResponse)
async def run_events(
    run: RunRow,
    state: State,
    request: Request,
    last_event_id: Annotated[str | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    """Stream the run's progress events. Resumes after `Last-Event-ID` on reconnect.

    The stream ends after the run's terminal event. If the run already finished and its
    event history has expired, one terminal event is synthesised from the stored run.
    """
    run_id = run.id
    finished = run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
    cursor = last_event_id or "0-0"

    if finished and not await state.events.read(run_id, after=cursor, block_ms=None, count=1):
        kind = (
            EventType.RUN_SUCCEEDED if run.status is RunStatus.SUCCEEDED else EventType.RUN_FAILED
        )
        event = RunEvent(
            type=kind, run_id=run_id, detail={"from": "stored run", "error": run.error}
        )
        yield ServerSentEvent(data=event, event=event.type.value)
        return

    while not await request.is_disconnected():
        batch = await state.events.read(run_id, after=cursor, block_ms=KEEPALIVE_MS)
        if not batch:
            yield ServerSentEvent(comment="keep-alive")
            continue
        for event_id, event in batch:
            cursor = event_id
            yield ServerSentEvent(data=event, event=event.type.value, id=event_id)
            if event.type in TERMINAL:
                return
