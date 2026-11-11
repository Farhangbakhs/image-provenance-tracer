"""Assets: the uploaded image, its fingerprints, metadata, credentials and runs."""

from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from origin_api import ratelimit
from origin_api.schemas import (
    AssetEvidence,
    AssetOut,
    CredentialsOut,
    EmbeddingOut,
    Fingerprints,
    MetadataOut,
    MetadataSummary,
    RunBrief,
    RunOut,
)
from origin_api.state import Session, State
from origin_core.db.models import Artefact, Asset, AuditEvent, Run
from origin_core.enums import Actor
from origin_core.pipeline.jobs import enqueue_run
from origin_core.pipeline.registry import STAGE_ORDER

router = APIRouter(prefix="/assets", tags=["assets"])


def _metadata_out(raw: dict[str, Any] | None) -> MetadataOut:
    if not raw or raw.get("status") != "ok":
        error = str(raw.get("error")) if raw else "metadata was not read"
        return MetadataOut(status="unavailable", error=error)
    return MetadataOut(
        status="ok",
        tool=raw.get("tool"),
        tool_version=raw.get("tool_version"),
        summary=MetadataSummary.model_validate(raw.get("summary") or {}),
        tag_count=len(cast(dict[str, Any], raw.get("raw") or {})),
    )


def _credentials_out(asset: Asset) -> CredentialsOut:
    report = dict(asset.c2pa_report or {})
    report.pop("manifest_store", None)
    report["state"] = asset.c2pa_state
    report.setdefault("trust_list", "unknown")
    return CredentialsOut.model_validate(report)


async def asset_out(session: Session, asset: Asset) -> AssetOut:
    original = await session.get_one(Artefact, asset.original_artefact_id)
    runs = (
        (
            await session.execute(
                select(Run).where(Run.asset_id == asset.id).order_by(Run.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return AssetOut(
        id=asset.id,
        case_id=asset.case_id,
        original_filename=asset.original_filename,
        content_type=asset.content_type,
        width=asset.width,
        height=asset.height,
        byte_size=original.byte_size,
        created_at=asset.created_at,
        fingerprints=Fingerprints(
            sha256=asset.sha256,
            phash=asset.phash,
            dhash=asset.dhash,
            pdq=asset.pdq,
            pdq_quality=asset.pdq_quality,
        ),
        metadata=_metadata_out(asset.metadata_raw),
        credentials=_credentials_out(asset),
        embedding=EmbeddingOut(
            status="computed" if asset.embedding_model else "pending",
            model=asset.embedding_model,
        ),
        display_url=f"/assets/{asset.id}/display",
        runs=[RunBrief(id=r.id, status=r.status, created_at=r.created_at) for r in runs],
    )


async def _asset_or_404(session: Session, asset_id: uuid.UUID) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


@router.get("/{asset_id}")
async def get_asset(asset_id: uuid.UUID, session: Session) -> AssetOut:
    return await asset_out(session, await _asset_or_404(session, asset_id))


@router.get("/{asset_id}/evidence")
async def get_asset_evidence(asset_id: uuid.UUID, session: Session) -> AssetEvidence:
    """Full exiftool output and C2PA manifest store, as stored."""
    asset = await _asset_or_404(session, asset_id)
    metadata = asset.metadata_raw or {}
    return AssetEvidence(
        metadata_raw=cast(dict[str, Any] | None, metadata.get("raw")),
        c2pa_manifest_store=cast(
            dict[str, Any] | None, (asset.c2pa_report or {}).get("manifest_store")
        ),
    )


@router.get(
    "/{asset_id}/display",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
async def get_display(asset_id: uuid.UUID, session: Session, state: State) -> Response:
    """The re-encoded display copy (oriented, metadata stripped). Never the original."""
    asset = await _asset_or_404(session, asset_id)
    if asset.display_artefact_id is None:
        raise HTTPException(status_code=404, detail="no display copy")
    display = await session.get_one(Artefact, asset.display_artefact_id)
    data = await state.blobs.get(display.storage_key)
    return Response(
        content=data,
        media_type=display.content_type,
        headers={
            # Content-addressed: the bytes behind this asset never change.
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{asset_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(ratelimit.runs)],
    responses={429: {"description": "Too many trace starts from this client; see Retry-After"}},
)
async def start_run(asset_id: uuid.UUID, session: Session, state: State) -> RunOut:
    """Start a trace of this asset. The run executes on the worker; follow it over SSE."""
    asset = await _asset_or_404(session, asset_id)
    run = Run(case_id=asset.case_id, asset_id=asset.id, providers=[])
    session.add(run)
    await session.flush()
    session.add(
        AuditEvent(
            case_id=asset.case_id,
            run_id=run.id,
            actor=Actor.ANALYST,
            action="run.requested",
            subject_type="asset",
            subject_id=asset.id,
            detail={},
        )
    )
    await session.commit()
    await session.refresh(run)
    await enqueue_run(state.jobs, run.id)
    return RunOut.from_row(run, list(STAGE_ORDER))
