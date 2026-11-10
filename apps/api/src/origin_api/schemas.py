"""Response models. These define the OpenAPI schema the web client is generated from."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from origin_core.enums import RunStatus


class Livez(BaseModel):
    status: Literal["ok"]
    version: str


class DependencyCheck(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None


class Readyz(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, DependencyCheck]


class StageState(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["running", "succeeded", "failed"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: dict[str, int] = {}
    quota: dict[str, int] = {}
    error: str | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    asset_id: uuid.UUID
    status: RunStatus
    providers: list[str]
    stages: dict[str, StageState]
    stage_order: list[str]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_row(cls, row: Any, stage_order: list[str]) -> RunOut:
        return cls(
            id=row.id,
            case_id=row.case_id,
            asset_id=row.asset_id,
            status=row.status,
            providers=list(row.providers),
            stages={k: StageState.model_validate(v) for k, v in dict(row.stages).items()},
            stage_order=stage_order,
            error=row.error,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
