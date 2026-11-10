"""Run progress events on Redis Streams.

Each run has one stream, `origin:run:<run_id>:events`. The worker appends; the API relays the
stream to browsers over server-sent events. Streams (unlike pub/sub) keep history, so a client
that connects late or reconnects with `Last-Event-ID` resumes exactly where it stopped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, Field
from redis.asyncio import Redis

STREAM_MAXLEN = 2000
STREAM_TTL_S = 7 * 24 * 3600


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    RUN_SUCCEEDED = "run.succeeded"
    RUN_FAILED = "run.failed"
    STAGE_STARTED = "stage.started"
    STAGE_SUCCEEDED = "stage.succeeded"
    STAGE_SKIPPED = "stage.skipped"
    STAGE_FAILED = "stage.failed"
    STAGE_PROGRESS = "stage.progress"


TERMINAL = frozenset({EventType.RUN_SUCCEEDED, EventType.RUN_FAILED})


class RunEvent(BaseModel):
    type: EventType
    run_id: uuid.UUID
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stage: str | None = None
    counts: dict[str, int] = {}
    detail: dict[str, Any] = {}


def stream_key(run_id: uuid.UUID) -> str:
    return f"origin:run:{run_id}:events"


class RunEventBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, event: RunEvent) -> str:
        key = stream_key(event.run_id)
        event_id = await self._redis.xadd(
            key, {"event": event.model_dump_json()}, maxlen=STREAM_MAXLEN, approximate=True
        )
        await self._redis.expire(key, STREAM_TTL_S)
        return event_id.decode() if isinstance(event_id, bytes) else str(event_id)

    async def read(
        self,
        run_id: uuid.UUID,
        *,
        after: str = "0-0",
        block_ms: int | None = 15_000,
        count: int = 100,
    ) -> list[tuple[str, RunEvent]]:
        """Events after `after`, waiting up to `block_ms` for new ones (None: do not wait).

        Returns an empty list on timeout.
        """
        if block_ms == 0:
            raise ValueError("block_ms=0 would block forever; use None for a non-blocking read")
        response = await self._redis.xread({stream_key(run_id): after}, block=block_ms, count=count)
        events: list[tuple[str, RunEvent]] = []
        for _stream, entries in cast(list[tuple[Any, list[tuple[Any, dict[Any, Any]]]]], response):
            for raw_id, fields in entries:
                event_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
                payload = fields.get(b"event", fields.get("event"))
                if not isinstance(payload, str | bytes):
                    raise ValueError(f"event {event_id} has no payload")
                events.append((event_id, RunEvent.model_validate_json(payload)))
        return events
