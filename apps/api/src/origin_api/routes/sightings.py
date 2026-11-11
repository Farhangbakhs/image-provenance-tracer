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
    ClaimOut,
    EvidenceOut,
    GradeOut,
    NarrativeOut,
    OverruleIn,
    RunAnalysisOut,
    RunSightingsOut,
    SightingOut,
    VariantEdgeOut,
    VariantOut,
)
from origin_api.state import Session, State
from origin_core.db.models import (
    Artefact,
    AuditEvent,
    Candidate,
    Claim,
    Narrative,
    NarrativeClaim,
    Run,
    Sighting,
    TimestampEvidence,
    Variant,
    VariantEdge,
)
from origin_core.enums import Actor, AnalystStatus
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
                variant_id=sighting.variant_id,
                reliability=sighting.reliability,
                credibility=sighting.credibility,
                grade_rationale=sighting.grade_rationale,
                analyst_status=sighting.analyst_status,
                analyst_note=sighting.analyst_note,
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


@router.get("/runs/{run_id}/analysis")
async def run_analysis(run_id: uuid.UUID, session: Session) -> RunAnalysisOut:
    """Variants and their edit edges, claims, narratives and grades for a run."""
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    sightings = list(
        (await session.execute(select(Sighting).where(Sighting.run_id == run_id))).scalars()
    )
    variants = list(
        (
            await session.execute(
                select(Variant).where(Variant.run_id == run_id).order_by(Variant.label)
            )
        ).scalars()
    )
    edges = list(
        (await session.execute(select(VariantEdge).where(VariantEdge.run_id == run_id))).scalars()
    )
    claims = list((await session.execute(select(Claim).where(Claim.run_id == run_id))).scalars())
    narratives = list(
        (
            await session.execute(
                select(Narrative).where(Narrative.run_id == run_id).order_by(Narrative.created_at)
            )
        ).scalars()
    )
    memberships = (
        await session.execute(
            select(NarrativeClaim).where(
                NarrativeClaim.narrative_id.in_([n.id for n in narratives])
            )
        )
    ).scalars()
    claims_of: dict[uuid.UUID, list[uuid.UUID]] = {}
    for member in memberships:
        claims_of.setdefault(member.narrative_id, []).append(member.claim_id)

    stage = cast(dict[str, Any], (run.stages or {}).get("branch") or {})
    return RunAnalysisOut(
        run_id=run.id,
        variants=[
            VariantOut(
                id=v.id,
                label=v.label,
                representative_sighting_id=v.representative_sighting_id,
                sighting_ids=[s.id for s in sightings if s.variant_id == v.id],
            )
            for v in variants
        ],
        edges=[
            VariantEdgeOut(
                parent_variant_id=e.parent_variant_id,
                child_variant_id=e.child_variant_id,
                kind=e.kind.value,
                reason=e.reason,
                evidence=dict(e.evidence),
            )
            for e in edges
        ],
        claims=[
            ClaimOut(
                id=c.id,
                sighting_id=c.sighting_id,
                event=c.event,
                place=c.place,
                claimed_date=c.claimed_date,
                actor_role=c.actor_role,
                stance=c.stance,
                quote=c.quote,
                quote_start=c.quote_start,
                quote_end=c.quote_end,
                language=c.language,
                translation=c.translation,
                llm_provider=c.llm_provider,
                llm_model=c.llm_model,
                prompt_version=c.prompt_version,
                analyst_status=c.analyst_status,
                analyst_note=c.analyst_note,
            )
            for c in claims
        ],
        narratives=[
            NarrativeOut(
                id=n.id,
                label=n.label,
                summary=n.summary,
                parent_narrative_id=n.parent_narrative_id,
                divergence_sighting_id=n.divergence_sighting_id,
                divergence_reason=n.divergence_reason,
                claim_ids=claims_of.get(n.id, []),
                llm_provider=n.llm_provider,
                llm_model=n.llm_model,
                prompt_version=n.prompt_version,
            )
            for n in narratives
        ],
        grades=[
            GradeOut(
                sighting_id=s.id,
                reliability=s.reliability,
                credibility=s.credibility,
                rationale=s.grade_rationale,
            )
            for s in sightings
        ],
        notes=cast(dict[str, str], stage.get("notes") or {}),
    )


async def _overrule(
    session: Session, row: Claim | Sighting, kind: str, body: OverruleIn, case_id: uuid.UUID
) -> None:
    previous = row.analyst_status.value
    row.analyst_status = AnalystStatus(body.status)
    row.analyst_note = body.note
    session.add(
        AuditEvent(
            case_id=case_id,
            run_id=row.run_id,
            actor=Actor.ANALYST,
            action=f"{kind}.{body.status}",
            subject_type=kind,
            subject_id=row.id,
            detail={"from": previous, "to": body.status, "note": body.note},
        )
    )
    await session.commit()


@router.patch("/claims/{claim_id}")
async def overrule_claim(claim_id: uuid.UUID, body: OverruleIn, session: Session) -> ClaimOut:
    """Accept or overrule a claim the model extracted. The claim is kept, with the decision."""
    claim = await session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    run = await session.get_one(Run, claim.run_id)
    await _overrule(session, claim, "claim", body, run.case_id)
    await session.refresh(claim)
    return ClaimOut.model_validate(claim, from_attributes=True)


@router.patch("/sightings/{sighting_id}")
async def overrule_sighting(
    sighting_id: uuid.UUID, body: OverruleIn, session: Session
) -> dict[str, str | None]:
    """Accept or overrule a match. The sighting and its evidence are kept, with the decision."""
    sighting = await session.get(Sighting, sighting_id)
    if sighting is None:
        raise HTTPException(status_code=404, detail="sighting not found")
    run = await session.get_one(Run, sighting.run_id)
    await _overrule(session, sighting, "sighting", body, run.case_id)
    return {"id": str(sighting.id), "analyst_status": body.status, "analyst_note": body.note}
