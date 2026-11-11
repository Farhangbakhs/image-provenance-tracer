"""The evidence pack: one JSON document holding a run's findings and an index of every artefact
behind them, each with its SHA-256, fetch time and storage key, so a reader can check them."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from origin_api.routes.sightings import run_analysis, run_sightings
from origin_api.schemas import RunAnalysisOut, RunOut, RunSightingsOut
from origin_api.state import Session
from origin_core.db.models import (
    Artefact,
    Asset,
    AuditEvent,
    Case,
    ProviderCall,
    Run,
    Sighting,
    TimestampEvidence,
)
from origin_core.pipeline.registry import stage_order
from origin_core.wording import EARLIEST_DISCLAIMER

router = APIRouter(tags=["export"])

PACK_FORMAT = "origin.evidence-pack.v1"


class PackCase(BaseModel):
    id: uuid.UUID
    title: str
    notes: str | None


class PackAsset(BaseModel):
    id: uuid.UUID
    original_filename: str | None
    content_type: str
    width: int
    height: int
    sha256: str
    phash: str
    dhash: str
    pdq: str
    embedding_model: str | None
    original_artefact_id: uuid.UUID
    display_artefact_id: uuid.UUID | None


class PackProviderCall(BaseModel):
    id: uuid.UUID
    provider: str
    request_hash: str
    params: dict[str, Any]
    status: str
    units: int
    raw_artefact_id: uuid.UUID | None
    error: str | None
    at: datetime


class PackArtefact(BaseModel):
    id: uuid.UUID
    kind: str
    sha256: str
    storage_key: str
    content_type: str
    byte_size: int
    source_url: str | None
    http_status: int | None
    fetched_at: datetime


class PackAuditEvent(BaseModel):
    at: datetime
    actor: str
    action: str
    subject_type: str | None
    subject_id: uuid.UUID | None
    detail: dict[str, Any]


class EvidencePack(BaseModel):
    format: str
    generated_at: datetime
    disclaimer: str
    case: PackCase
    asset: PackAsset
    run: RunOut
    sightings: RunSightingsOut
    analysis: RunAnalysisOut
    provider_calls: list[PackProviderCall]
    artefacts: list[PackArtefact]
    audit: list[PackAuditEvent]


@router.get("/runs/{run_id}/evidence-pack", response_model=EvidencePack)
async def evidence_pack(
    run_id: uuid.UUID, session: Session, download: bool = False
) -> EvidencePack | JSONResponse:
    """With `download=true`, served as an attachment named after the run."""
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    case = await session.get_one(Case, run.case_id)
    asset = await session.get_one(Asset, run.asset_id)
    original = await session.get_one(Artefact, asset.original_artefact_id)
    sightings_out = await run_sightings(run_id, session)
    analysis_out = await run_analysis(run_id, session)

    calls = list(
        (
            await session.execute(
                select(ProviderCall)
                .where(ProviderCall.run_id == run_id)
                .order_by(ProviderCall.created_at)
            )
        ).scalars()
    )
    sightings = list(
        (await session.execute(select(Sighting).where(Sighting.run_id == run_id))).scalars()
    )
    evidence = list(
        (
            await session.execute(
                select(TimestampEvidence).where(
                    TimestampEvidence.sighting_id.in_([s.id for s in sightings])
                )
            )
        ).scalars()
    )
    referenced: set[uuid.UUID] = {asset.original_artefact_id}
    if asset.display_artefact_id:
        referenced.add(asset.display_artefact_id)
    referenced.update(c.raw_artefact_id for c in calls if c.raw_artefact_id)
    for s in sightings:
        referenced.add(s.image_artefact_id)
        if s.page_artefact_id:
            referenced.add(s.page_artefact_id)
    referenced.update(e.artefact_id for e in evidence if e.artefact_id)
    artefacts = list(
        (
            await session.execute(
                select(Artefact).where(Artefact.id.in_(referenced)).order_by(Artefact.fetched_at)
            )
        ).scalars()
    )
    audit = list(
        (
            await session.execute(
                select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id)
            )
        ).scalars()
    )

    pack = EvidencePack(
        format=PACK_FORMAT,
        generated_at=datetime.now(UTC),
        disclaimer=EARLIEST_DISCLAIMER,
        case=PackCase(id=case.id, title=case.title, notes=case.notes),
        asset=PackAsset(
            id=asset.id,
            original_filename=asset.original_filename,
            content_type=asset.content_type,
            width=asset.width,
            height=asset.height,
            sha256=original.sha256,
            phash=asset.phash,
            dhash=asset.dhash,
            pdq=asset.pdq,
            embedding_model=asset.embedding_model,
            original_artefact_id=asset.original_artefact_id,
            display_artefact_id=asset.display_artefact_id,
        ),
        run=RunOut.from_row(run, stage_order(run.stages)),
        sightings=sightings_out,
        analysis=analysis_out,
        provider_calls=[
            PackProviderCall(
                id=c.id,
                provider=c.provider,
                request_hash=c.request_hash,
                params=dict(c.params or {}),
                status=c.status.value,
                units=c.units,
                raw_artefact_id=c.raw_artefact_id,
                error=c.error,
                at=c.created_at,
            )
            for c in calls
        ],
        artefacts=[
            PackArtefact(
                id=a.id,
                kind=a.kind.value,
                sha256=a.sha256,
                storage_key=a.storage_key,
                content_type=a.content_type,
                byte_size=a.byte_size,
                source_url=a.source_url,
                http_status=a.http_status,
                fetched_at=a.fetched_at,
            )
            for a in artefacts
        ],
        audit=[
            PackAuditEvent(
                at=e.at,
                actor=e.actor.value,
                action=e.action,
                subject_type=e.subject_type,
                subject_id=e.subject_id,
                detail=dict(e.detail or {}),
            )
            for e in audit
        ],
    )
    if not download:
        return pack
    return JSONResponse(
        pack.model_dump(mode="json"),
        headers={
            "Content-Disposition": f'attachment; filename="origin-run-{run_id}.json"',
        },
    )
