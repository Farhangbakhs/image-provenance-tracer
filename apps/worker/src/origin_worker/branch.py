"""The branch stage: variants, claims, narratives and grades for a run's sightings.

variants    cluster sightings into variants and derive edit edges (no model involved)
claims      ask the language model what each page claims its copy shows; every stored claim
            quotes the page verbatim and points at its sighting
narratives  group claims; the root is the narrative of the earliest-dated claim, and every other
            narrative branches from it at its earliest sighting (the divergence point)
grading     Admiralty reliability per source and credibility per sighting, with rationale

Without a configured model, variants and grades are still produced and the stage notes why
claims and narratives were skipped.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import structlog
from sqlalchemy import delete, select, update

from origin_core.db.models import (
    Artefact,
    Claim,
    Narrative,
    NarrativeClaim,
    Sighting,
    Source,
    TimestampEvidence,
    Variant,
    VariantEdge,
)
from origin_core.enums import BoundType, Confidence, EvidenceKind, SourceKind, VariantEdgeKind
from origin_core.grading import PROOF_KINDS, UNGRADED_RATIONALE, EvidenceFact, credibility
from origin_core.grading import RULE_VERSION as GRADING_VERSION
from origin_core.ingest.hashes import fingerprint
from origin_core.ingest.validate import decode_rgb
from origin_core.llm.base import LLMError
from origin_core.llm.prompts import claim as claim_prompt
from origin_core.llm.prompts import narrative as narrative_prompt
from origin_core.llm.registry import LLMSetup
from origin_core.llm.runner import LLMOutputRejected, LLMRunner
from origin_core.pages import Page, caption_for, main_text, parse_page
from origin_core.pipeline.runner import StageContext, StageResult
from origin_core.storage import BlobStore
from origin_worker.matching.thresholds import Thresholds
from origin_worker.variants import Item, build_variant_graph

log = structlog.get_logger(__name__)
_FAR = datetime.max


def _seen(sighting: Sighting) -> str:
    return sighting.date_upper.isoformat() if sighting.date_upper else "unknown"


def _date_key(sighting: Sighting) -> datetime:
    return (sighting.date_upper or _FAR).replace(tzinfo=None)


@dataclass
class BranchStage:
    blobs: BlobStore
    thresholds: Thresholds
    llm: LLMSetup
    llm_runner: LLMRunner | None
    name: str = "branch"

    async def run(self, ctx: StageContext) -> StageResult:
        async with ctx.sessions() as session:
            sightings = list(
                (
                    await session.execute(select(Sighting).where(Sighting.run_id == ctx.run_id))
                ).scalars()
            )
        sightings.sort(key=_date_key)
        counts: dict[str, int] = {"sightings": len(sightings)}
        notes: dict[str, str] = {}

        await self._clear(ctx)
        counts |= await self._variants(ctx, sightings)

        if self.llm.provider is None or self.llm_runner is None:
            notes["claims"] = f"skipped: no language model ({self.llm.unavailable})"
        else:
            claims, failures = await self._claims(ctx, sightings)
            counts["claims"] = len(claims)
            if failures:
                notes["claims"] = f"{failures} page(s) gave no valid claim after retries"
            if claims:
                narratives, note = await self._narratives(ctx, sightings, claims)
                counts["narratives"] = narratives
                if note:
                    notes["narratives"] = note

        counts["graded"] = await self._grade(ctx, sightings)
        return StageResult(counts=counts, notes=notes)

    async def _clear(self, ctx: StageContext) -> None:
        async with ctx.sessions.begin() as session:
            # Narratives first: the database refuses a narrative left without claims.
            await session.execute(delete(Narrative).where(Narrative.run_id == ctx.run_id))
            await session.execute(delete(Claim).where(Claim.run_id == ctx.run_id))
            await session.execute(delete(VariantEdge).where(VariantEdge.run_id == ctx.run_id))
            await session.execute(
                update(Sighting).where(Sighting.run_id == ctx.run_id).values(variant_id=None)
            )
            await session.execute(delete(Variant).where(Variant.run_id == ctx.run_id))

    # --- variants ------------------------------------------------------------------------

    async def _variants(self, ctx: StageContext, sightings: list[Sighting]) -> dict[str, int]:
        items: list[Item] = []
        for sighting in sightings:
            async with ctx.sessions() as session:
                artefact = await session.get_one(Artefact, sighting.image_artefact_id)
            data = await self.blobs.get(artefact.storage_key)

            image = await asyncio.to_thread(decode_rgb, data)
            prints = await asyncio.to_thread(fingerprint, data, image)
            items.append(Item(str(sighting.id), prints, image, sighting.date_upper))

        graph = await asyncio.to_thread(build_variant_graph, items, self.thresholds)
        variant_ids: list[uuid.UUID] = []
        async with ctx.sessions.begin() as session:
            for index, variant in enumerate(graph.variants, start=1):
                row = Variant(
                    run_id=ctx.run_id,
                    label=f"V{index}",
                    representative_sighting_id=uuid.UUID(variant.representative.key),
                )
                session.add(row)
                await session.flush()
                variant_ids.append(row.id)
                await session.execute(
                    update(Sighting)
                    .where(Sighting.id.in_([uuid.UUID(i.key) for i in variant.members]))
                    .values(variant_id=row.id)
                )
            for edge in graph.edges:
                for kind in edge.kinds:
                    session.add(
                        VariantEdge(
                            run_id=ctx.run_id,
                            parent_variant_id=variant_ids[edge.parent],
                            child_variant_id=variant_ids[edge.child],
                            kind=VariantEdgeKind(kind),
                            reason=edge.reason,
                            evidence=edge.evidence,
                        )
                    )
        return {"variants": len(graph.variants), "variant_edges": len(graph.edges)}

    # --- claims --------------------------------------------------------------------------

    async def _claims(
        self, ctx: StageContext, sightings: list[Sighting]
    ) -> tuple[list[Claim], int]:
        assert self.llm.provider is not None and self.llm_runner is not None
        claims: list[Claim] = []
        failures = 0
        for index, sighting in enumerate(sightings, start=1):
            if sighting.page_artefact_id is None:
                continue
            async with ctx.sessions() as session:
                page = await session.get_one(Artefact, sighting.page_artefact_id)
            body = await self.blobs.get(page.storage_key)
            url = page.source_url or sighting.page_url or ""
            parsed, caption, text = await asyncio.to_thread(
                _read_page, url, body, sighting.image_url
            )
            source = claim_prompt.build_source(parsed.title, caption, text)
            if not source.text:
                continue
            domain = urlsplit(url).hostname or "an unknown site"
            prompt = claim_prompt.build_prompt(f"s{index}", domain, source)
            try:
                out, reply = await self.llm_runner.complete_validated(
                    self.llm.provider,
                    prompt,
                    claim_prompt.ClaimOut,
                    check=claim_prompt.check(source),
                    run_id=ctx.run_id,
                )
            except (LLMOutputRejected, LLMError) as exc:
                failures += 1
                log.warning("branch.claim_failed", sighting=str(sighting.id), error=str(exc))
                continue
            async with ctx.sessions.begin() as session:
                await session.execute(
                    update(Sighting)
                    .where(Sighting.id == sighting.id)
                    .values(extracted_text=source.text, language=out.language)
                )
                if not out.has_claim or not out.quote:
                    continue
                span = claim_prompt.locate_quote(source, out.quote)
                assert span is not None  # guaranteed by the validator
                row = Claim(
                    run_id=ctx.run_id,
                    sighting_id=sighting.id,
                    event=out.event,
                    place=out.place,
                    claimed_date=out.date_text,
                    claimed_date_lower=_day(out.date_iso),
                    claimed_date_upper=_day(out.date_iso),
                    actor_role=out.actor_role,
                    stance=out.stance,
                    quote=source.text[span[0] : span[1]],
                    quote_start=span[0],
                    quote_end=span[1],
                    language=out.language,
                    translation=out.translation,
                    llm_provider=reply.provider,
                    llm_model=reply.model,
                    prompt_version=reply.prompt_version,
                )
                session.add(row)
                await session.flush()
                claims.append(row)
            await ctx.progress(self.name, claims=len(claims))
        return claims, failures

    # --- narratives ----------------------------------------------------------------------

    async def _narratives(
        self, ctx: StageContext, sightings: list[Sighting], claims: list[Claim]
    ) -> tuple[int, str | None]:
        assert self.llm.provider is not None and self.llm_runner is not None
        by_id = {s.id: s for s in sightings}
        ordered = sorted(claims, key=lambda c: _date_key(by_id[c.sighting_id]))
        aliases = {f"c{i}": claim for i, claim in enumerate(ordered, start=1)}
        lines = [
            narrative_prompt.ClaimLine(
                alias=alias,
                seen=_seen(by_id[claim.sighting_id]),
                event=claim.event,
                place=claim.place,
                date_text=claim.claimed_date,
                stance=claim.stance,
                quote=claim.quote,
            )
            for alias, claim in aliases.items()
        ]
        try:
            out, reply = await self.llm_runner.complete_validated(
                self.llm.provider,
                narrative_prompt.build_prompt(lines),
                narrative_prompt.NarrativesOut,
                check=narrative_prompt.check(list(aliases)),
                run_id=ctx.run_id,
            )
        except (LLMOutputRejected, LLMError) as exc:
            return 0, f"narratives not formed: {exc}"

        def earliest_sighting(claim_ids: list[str]) -> Sighting:
            return min((by_id[aliases[cid].sighting_id] for cid in claim_ids), key=_date_key)

        # The root is decided by the evidence: the narrative holding the earliest-dated claim.
        root_index = next(i for i, n in enumerate(out.narratives) if "c1" in n.claim_ids)
        order = [root_index] + [i for i in range(len(out.narratives)) if i != root_index]
        async with ctx.sessions.begin() as session:
            root_id: uuid.UUID | None = None
            for index in order:
                item = out.narratives[index]
                diverges_at = earliest_sighting(item.claim_ids)
                row = Narrative(
                    run_id=ctx.run_id,
                    label=item.label,
                    summary=item.summary,
                    parent_narrative_id=root_id,
                    divergence_sighting_id=diverges_at.id,
                    divergence_reason=None
                    if root_id is None
                    else (
                        item.reason or f"contradicts the earliest narrative on {item.contradiction}"
                    ),
                    llm_provider=reply.provider,
                    llm_model=reply.model,
                    prompt_version=reply.prompt_version,
                )
                session.add(row)
                await session.flush()
                for cid in item.claim_ids:
                    session.add(NarrativeClaim(narrative_id=row.id, claim_id=aliases[cid].id))
                await session.flush()
                if root_id is None:
                    root_id = row.id
        return len(out.narratives), None

    # --- grading -------------------------------------------------------------------------

    async def _grade(self, ctx: StageContext, sightings: list[Sighting]) -> int:
        async with ctx.sessions.begin() as session:
            for sighting in sightings:
                domain = (urlsplit(sighting.page_url or sighting.image_url).hostname or "").lower()
                source = (
                    await session.execute(select(Source).where(Source.key == domain))
                ).scalar_one_or_none()
                if source is None:
                    source = Source(
                        kind=SourceKind.DOMAIN,
                        key=domain,
                        display_name=domain,
                        rationale=UNGRADED_RATIONALE,
                    )
                    session.add(source)
                    await session.flush()
                evidence = list(
                    (
                        await session.execute(
                            select(TimestampEvidence).where(
                                TimestampEvidence.sighting_id == sighting.id
                            )
                        )
                    ).scalars()
                )
                facts = [EvidenceFact(e.kind, e.bound, e.confidence) for e in evidence]
                contradicted = contradicted_claim(evidence)
                grade = credibility(sighting.match_class, facts, contradicted=contradicted)
                await session.execute(
                    update(Sighting)
                    .where(Sighting.id == sighting.id)
                    .values(
                        source_id=source.id,
                        reliability=source.reliability,
                        credibility=grade.grade,
                        grade_rationale=(
                            f"{grade.rationale} Source {source.reliability}: "
                            f"{source.rationale} ({GRADING_VERSION})"
                        ),
                    )
                )
        return len(sightings)


def _read_page(url: str, body: bytes, image_url: str) -> tuple[Page, str | None, str | None]:
    return parse_page(url, body), caption_for(url, body, image_url), main_text(body)


def contradicted_claim(evidence: list[TimestampEvidence]) -> bool:
    """True if the page's stated date is impossible given independent proofs.

    A stated date after an archive capture or platform timestamp (the copy already existed), or
    before the picture was taken or signed, contradicts the evidence.
    """
    stated = [e.value for e in evidence if e.kind is EvidenceKind.PAGE_METADATA]
    if not stated:
        return False
    ceilings = [
        e.value
        for e in evidence
        if e.kind in PROOF_KINDS and e.bound in (BoundType.NO_LATER_THAN, BoundType.EXACT)
    ]
    floors = [
        e.value
        for e in evidence
        if e.bound is BoundType.NO_EARLIER_THAN and e.confidence is Confidence.HIGH
    ]
    upper = min(ceilings) if ceilings else None
    lower = max(floors) if floors else None
    return any((upper and v > upper) or (lower and v < lower) for v in stated)


def _day(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None
