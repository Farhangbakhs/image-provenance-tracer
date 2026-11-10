"""PipelineRunner: executes a run's stages in order, resumably and audibly.

Every stage transition is written to `runs.stages` (start, end, counts, error), to the
append-only audit log, and to the run's event stream. A stage already marked succeeded is
skipped, so a retried job resumes after the last completed stage instead of repeating work
(and spending quota) twice.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from origin_core.db.models import AuditEvent, Run
from origin_core.enums import Actor, RunStatus
from origin_core.pipeline.events import EventType, RunEvent, RunEventBus

log = structlog.get_logger(__name__)


@dataclass
class StageContext:
    run_id: uuid.UUID
    sessions: async_sessionmaker[AsyncSession]
    events: RunEventBus

    async def progress(self, stage: str, **counts: int) -> None:
        await self.events.publish(
            RunEvent(type=EventType.STAGE_PROGRESS, run_id=self.run_id, stage=stage, counts=counts)
        )


@dataclass(frozen=True)
class StageResult:
    counts: dict[str, int] = field(default_factory=dict[str, int])
    quota: dict[str, int] = field(default_factory=dict[str, int])
    #: Short explanations shown with the stage, e.g. why a provider did not run.
    notes: dict[str, str] = field(default_factory=dict[str, str])


class Stage(Protocol):
    name: str

    async def run(self, ctx: StageContext) -> StageResult: ...


class RunNotFound(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class PipelineRunner:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        events: RunEventBus,
        stages: Sequence[Stage],
    ) -> None:
        names = [stage.name for stage in stages]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate stage names: {names}")
        self._sessions = sessions
        self._events = events
        self._stages = list(stages)

    async def execute(self, run_id: uuid.UUID) -> RunStatus:
        ctx = StageContext(run_id=run_id, sessions=self._sessions, events=self._events)
        bound = log.bind(run_id=str(run_id))

        async with self._sessions.begin() as session:
            run = await session.get(Run, run_id, with_for_update=True)
            if run is None:
                raise RunNotFound(str(run_id))
            if run.status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}:
                return run.status
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or datetime.now(UTC)
            run.error = None
            completed = {
                name
                for name, state in run.stages.items()
                if isinstance(state, dict) and state.get("status") == "succeeded"
            }
            self._audit(session, run, "run.started", {"stages": [s.name for s in self._stages]})
        await self._events.publish(RunEvent(type=EventType.RUN_STARTED, run_id=run_id))
        bound.info("run.started")

        for stage in self._stages:
            if stage.name in completed:
                await self._events.publish(
                    RunEvent(type=EventType.STAGE_SKIPPED, run_id=run_id, stage=stage.name)
                )
                continue
            await self._set_stage(run_id, stage.name, {"status": "running", "started_at": _now()})
            await self._events.publish(
                RunEvent(type=EventType.STAGE_STARTED, run_id=run_id, stage=stage.name)
            )
            try:
                result = await stage.run(ctx)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                bound.exception("stage.failed", stage=stage.name)
                await self._set_stage(
                    run_id,
                    stage.name,
                    {"status": "failed", "finished_at": _now(), "error": error},
                    run_status=RunStatus.FAILED,
                    run_error=f"stage {stage.name} failed: {error}",
                )
                await self._events.publish(
                    RunEvent(
                        type=EventType.STAGE_FAILED,
                        run_id=run_id,
                        stage=stage.name,
                        detail={"error": error},
                    )
                )
                await self._events.publish(
                    RunEvent(type=EventType.RUN_FAILED, run_id=run_id, detail={"error": error})
                )
                return RunStatus.FAILED
            await self._set_stage(
                run_id,
                stage.name,
                {
                    "status": "succeeded",
                    "finished_at": _now(),
                    "counts": result.counts,
                    "quota": result.quota,
                    "notes": result.notes,
                },
            )
            await self._events.publish(
                RunEvent(
                    type=EventType.STAGE_SUCCEEDED,
                    run_id=run_id,
                    stage=stage.name,
                    counts=result.counts,
                )
            )

        async with self._sessions.begin() as session:
            run = await session.get_one(Run, run_id, with_for_update=True)
            run.status = RunStatus.SUCCEEDED
            run.finished_at = datetime.now(UTC)
            self._audit(session, run, "run.succeeded", {})
        await self._events.publish(RunEvent(type=EventType.RUN_SUCCEEDED, run_id=run_id))
        bound.info("run.succeeded")
        return RunStatus.SUCCEEDED

    async def _set_stage(
        self,
        run_id: uuid.UUID,
        stage: str,
        update: dict[str, Any],
        *,
        run_status: RunStatus | None = None,
        run_error: str | None = None,
    ) -> None:
        async with self._sessions.begin() as session:
            run = await session.get_one(Run, run_id, with_for_update=True)
            stages = dict(run.stages)
            previous = stages.get(stage)
            merged: dict[str, Any] = (
                dict(cast(dict[str, Any], previous)) if isinstance(previous, dict) else {}
            )
            merged.update(update)
            stages[stage] = merged
            run.stages = stages  # reassign so the JSONB change is persisted
            if run_status is not None:
                run.status = run_status
                run.finished_at = datetime.now(UTC)
                run.error = run_error
            self._audit(session, run, f"stage.{update['status']}", {"stage": stage, **update})

    @staticmethod
    def _audit(session: AsyncSession, run: Run, action: str, detail: dict[str, Any]) -> None:
        session.add(
            AuditEvent(
                case_id=run.case_id,
                run_id=run.id,
                actor=Actor.SYSTEM,
                action=action,
                subject_type="run",
                subject_id=run.id,
                detail=detail,
            )
        )
