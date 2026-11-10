"""Verified, dated sightings of a run, and the fetched copy of each sighting's image."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from origin_api.schemas import (
    CandidateCounts,
    EvidenceOut,
    RunSightingsOut,
    SightingOut,
)
from origin_api.state import Session, State
from origin_core.db.models import Artefact, Candidate, Run, Sighting, TimestampEvidence
from origin_core.ingest.validate import MIME_TYPES, sniff_format

router = APIRouter(tags=["sightings"])

_FAR_FUTURE = datetime.max.replace(tzinfo=None)


def _evidence_out(row: TimestampEvidence) -> EvidenceOut:
    return EvidenceOut(
        id=row.id,
        kind=row.kind.value,
        value=row.value,
        bound=row.bound.value,
        confidence=row.confidence.value,
        source_url=row.source_url,
        detail=dict(row.detail or {}),
    )


def earliest_key(sighting: Sighting) -> tuple[datetime, datetime]:
    """Order by the proven upper bound ("existed no later than"), then the lower bound.

    The upper bound is what the evidence proves; sorting on it never lets a mere claim make a
    copy look earlier than it can be shown to be.
    """
    upper = sighting.date_upper.replace(tzinfo=None) if sighting.date_upper else _FAR_FUTURE
    lower = sighting.date_lower.replace(tzinfo=None) if sighting.date_lower else upper
    return upper, lower


@router.get("/runs/{run_id}/sightings")
async def run_sightings(run_id: uuid.UUID, session: Session) -> RunSightingsOut:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    rows = (
        await session.execute(
            select(Sighting, Candidate)
            .join(Candidate, Candidate.id == Sighting.candidate_id)
            .where(Sighting.run_id == run_id)
        )
    ).all()
    evidence_rows = (
        (
            await session.execute(
                select(TimestampEvidence).where(
                    TimestampEvidence.sighting_id.in_([s.id for s, _ in rows])
                )
            )
        )
        .scalars()
        .all()
    )
    by_sighting: dict[uuid.UUID, list[TimestampEvidence]] = {}
    for row in evidence_rows:
        by_sighting.setdefault(row.sighting_id, []).append(row)

    statuses = Counter(
        (
            await session.execute(select(Candidate.status).where(Candidate.run_id == run_id))
        ).scalars()
    )
    ordered = sorted(rows, key=lambda pair: earliest_key(pair[0]))
    dated = [s for s, _ in ordered if s.date_upper is not None]

    sightings: list[SightingOut] = []
    for sighting, candidate in ordered:
        evidence = sorted(by_sighting.get(sighting.id, []), key=lambda e: e.value)
        deciding = next((e for e in evidence if e.id == sighting.deciding_evidence_id), None)
        sightings.append(
            SightingOut(
                id=sighting.id,
                provider=candidate.provider,
                page_url=sighting.page_url,
                image_url=sighting.image_url,
                domain=urlsplit(sighting.page_url or sighting.image_url).hostname or "",
                title=sighting.title,
                match_class=sighting.match_class.value,
                match_reason=candidate.reject_reason,
                sscd_cosine=sighting.sscd_cosine,
                phash_distance=sighting.phash_distance,
                pdq_distance=sighting.pdq_distance,
                transform=sighting.transform,
                threshold_version=sighting.threshold_version,
                date_lower=sighting.date_lower,
                date_upper=sighting.date_upper,
                date_confidence=sighting.date_confidence.value,
                dating_rule_version=sighting.dating_rule_version,
                deciding=_evidence_out(deciding) if deciding else None,
                evidence=[_evidence_out(e) for e in evidence],
                image_url_local=f"/sightings/{sighting.id}/image",
            )
        )

    stage_state = cast(dict[str, Any], (run.stages or {}).get("discover") or {})
    return RunSightingsOut(
        run_id=run.id,
        status=run.status,
        earliest_sighting_id=dated[0].id if dated else None,
        candidates=CandidateCounts(**{status.value: n for status, n in statuses.items()}),
        notes=cast(dict[str, str], stage_state.get("notes") or {}),
        sightings=sightings,
    )


@router.get(
    "/sightings/{sighting_id}/image",
    response_class=Response,
    responses={
        200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}, "image/gif": {}}}
    },
)
async def sighting_image(sighting_id: uuid.UUID, session: Session, state: State) -> Response:
    """The copy ORIGIN fetched, served only as the image type its bytes prove it to be."""
    sighting = await session.get(Sighting, sighting_id)
    if sighting is None:
        raise HTTPException(status_code=404, detail="sighting not found")
    artefact = await session.get_one(Artefact, sighting.image_artefact_id)
    data = await state.blobs.get(artefact.storage_key)
    fmt = sniff_format(data)
    if fmt is None:
        raise HTTPException(status_code=415, detail="stored bytes are not a supported image")
    return Response(
        content=data,
        media_type=MIME_TYPES[fmt],
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        },
    )
