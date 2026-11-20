"""The run's sightings: ordered by what the evidence proves, with the deciding signal attached."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import SeedRun

from origin_core.db.models import (
    Artefact,
    Candidate,
    ProviderCall,
    Run,
    Sighting,
    TimestampEvidence,
)
from origin_core.db.session import make_sessionmaker
from origin_core.enums import (
    ArtefactKind,
    BoundType,
    CandidateStatus,
    Confidence,
    DateConfidence,
    EvidenceKind,
    MatchClass,
    ProviderCallStatus,
)
from origin_core.storage import FilesystemBlobStore

pytestmark = [pytest.mark.db, pytest.mark.redis]


def t(day: int) -> datetime:
    return datetime(2024, 3, day, tzinfo=UTC)


async def _seed_sightings(
    engine: AsyncEngine, run_id: uuid.UUID, blobs: FilesystemBlobStore
) -> dict[str, uuid.UUID]:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(out, format="PNG")
    blob = await blobs.put(out.getvalue(), "image/png")
    ids: dict[str, uuid.UUID] = {}
    async with make_sessionmaker(engine).begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                stages={
                    "discover": {
                        "status": "succeeded",
                        "notes": {"lens": "not queried: SERPAPI_API_KEY is not set"},
                    }
                }
            )
        )
        call = ProviderCall(
            run_id=run_id, provider="vision", request_hash="e" * 64, status=ProviderCallStatus.OK
        )
        session.add(call)
        await session.flush()
        for name, upper, lower, confidence in (
            ("late", t(20), None, DateConfidence.HIGH),
            ("early", t(10), t(8), DateConfidence.MEDIUM),
        ):
            candidate = Candidate(
                run_id=run_id,
                provider_call_id=call.id,
                provider="vision",
                page_url=f"https://{name}.example/page",
                status=CandidateStatus.VERIFIED,
                reject_reason="pHash 2 <= 8",
            )
            artefact = Artefact(
                kind=ArtefactKind.FETCHED_IMAGE,
                sha256=blob.sha256,
                storage_key=blob.key,
                content_type="text/html",  # what a hostile server might claim
                byte_size=blob.byte_size,
            )
            session.add_all([candidate, artefact])
            await session.flush()
            sighting = Sighting(
                run_id=run_id,
                candidate_id=candidate.id,
                image_artefact_id=artefact.id,
                page_url=candidate.page_url,
                image_url=f"https://{name}.example/i.png",
                match_class=MatchClass.NEAR_DUPLICATE,
                threshold_version="match.v2",
                date_upper=upper,
                date_lower=lower,
                date_confidence=confidence,
                dating_rule_version="dating.v1",
            )
            session.add(sighting)
            await session.flush()
            evidence = TimestampEvidence(
                sighting_id=sighting.id,
                kind=EvidenceKind.WAYBACK_PAGE,
                value=upper,
                bound=BoundType.NO_LATER_THAN,
                confidence=Confidence.HIGH,
                source_url=candidate.page_url,
            )
            session.add(evidence)
            await session.flush()
            sighting.deciding_evidence_id = evidence.id
            ids[name] = sighting.id
        session.add(
            Candidate(
                run_id=run_id,
                provider_call_id=call.id,
                provider="vision",
                image_url="https://x.example/y.jpg",
                status=CandidateStatus.UNRELATED,
            )
        )
    return ids


async def test_sightings_are_ordered_by_proven_date(
    client: httpx.AsyncClient, db_engine: AsyncEngine, seed_run: SeedRun, tmp_path: Path
) -> None:
    run_id = await seed_run()
    ids = await _seed_sightings(db_engine, run_id, FilesystemBlobStore(tmp_path / "blobs"))

    body = (await client.get(f"/runs/{run_id}/sightings")).json()
    assert [s["id"] for s in body["sightings"]] == [str(ids["early"]), str(ids["late"])]
    assert body["earliest_sighting_id"] == str(ids["early"])
    assert body["candidates"] == {
        "pending": 0,
        "verified": 2,
        "unrelated": 1,
        "fetch_failed": 0,
        "blocked": 0,
    }
    assert body["notes"] == {"lens": "not queried: SERPAPI_API_KEY is not set"}
    first = body["sightings"][0]
    assert first["domain"] == "early.example"
    assert first["deciding"]["kind"] == "wayback_page"
    assert first["date_confidence"] == "medium"

    image = await client.get(first["image_url_local"])
    assert image.status_code == 200
    # Served as the type the bytes prove, not the type the remote server claimed.
    assert image.headers["content-type"] == "image/png"
    assert image.headers["content-security-policy"] == "default-src 'none'"


async def test_unknown_run_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/runs/{uuid.uuid4()}/sightings")).status_code == 404


async def test_analysis_and_overrule(
    client: httpx.AsyncClient, db_engine: AsyncEngine, seed_run: SeedRun, tmp_path: Path
) -> None:
    from origin_core.db.models import Claim, Narrative, NarrativeClaim, Variant
    from origin_core.enums import AnalystStatus

    run_id = await seed_run()
    ids = await _seed_sightings(db_engine, run_id, FilesystemBlobStore(tmp_path / "blobs"))
    async with make_sessionmaker(db_engine).begin() as session:
        variant = Variant(run_id=run_id, label="V1", representative_sighting_id=ids["early"])
        claim = Claim(
            run_id=run_id,
            sighting_id=ids["early"],
            event="flood",
            place="Valencia",
            quote="Floodwater in Valencia",
            quote_start=0,
            quote_end=22,
            llm_provider="gemini",
            llm_model="gemini-3.5-flash-lite",
            prompt_version="claim.v1",
        )
        session.add_all([variant, claim])
        await session.flush()
        narrative = Narrative(
            run_id=run_id,
            label="Flood in Valencia",
            divergence_sighting_id=ids["early"],
            llm_provider="gemini",
            llm_model="gemini-3.5-flash-lite",
            prompt_version="narrative.v1",
        )
        session.add(narrative)
        await session.flush()
        session.add(NarrativeClaim(narrative_id=narrative.id, claim_id=claim.id))
        await session.execute(
            update(Sighting).where(Sighting.id == ids["early"]).values(variant_id=variant.id)
        )
        claim_id, narrative_id = claim.id, narrative.id

    body = (await client.get(f"/runs/{run_id}/analysis")).json()
    assert [v["label"] for v in body["variants"]] == ["V1"]
    assert body["variants"][0]["sighting_ids"] == [str(ids["early"])]
    assert body["claims"][0]["quote"] == "Floodwater in Valencia"
    assert body["narratives"][0]["claim_ids"] == [str(claim_id)]
    assert body["narratives"][0]["id"] == str(narrative_id)

    overruled = await client.patch(
        f"/claims/{claim_id}", json={"status": "overruled", "note": "sarcasm, not a claim"}
    )
    assert overruled.status_code == 200
    assert overruled.json()["analyst_status"] == AnalystStatus.OVERRULED.value
    match = await client.patch(f"/sightings/{ids['late']}", json={"status": "overruled"})
    assert match.json()["analyst_status"] == "overruled"
    listed = (await client.get(f"/runs/{run_id}/sightings")).json()["sightings"]
    assert {s["id"]: s["analyst_status"] for s in listed}[str(ids["late"])] == "overruled"
    assert (
        await client.patch(f"/claims/{uuid.uuid4()}", json={"status": "accepted"})
    ).status_code == 404


async def test_evidence_pack_indexes_every_artefact(
    client: httpx.AsyncClient, db_engine: AsyncEngine, seed_run: SeedRun, tmp_path: Path
) -> None:
    run_id = await seed_run()
    ids = await _seed_sightings(db_engine, run_id, FilesystemBlobStore(tmp_path / "blobs"))

    pack = (await client.get(f"/runs/{run_id}/evidence-pack")).json()
    assert pack["format"] == "origin.evidence-pack.v1"
    assert pack["disclaimer"] == "Earliest found in indexed sources. Earlier copies may exist."
    assert pack["sightings"]["earliest_sighting_id"] == str(ids["early"])
    assert [c["provider"] for c in pack["provider_calls"]] == ["vision"]
    artefact_ids = {a["id"] for a in pack["artefacts"]}
    # The query image and each sighting's fetched copy, each with its hash and fetch time.
    assert pack["asset"]["original_artefact_id"] in artefact_ids
    assert len(artefact_ids) >= 3
    for artefact in pack["artefacts"]:
        assert len(artefact["sha256"]) == 64
        assert artefact["fetched_at"] and artefact["storage_key"]

    download = await client.get(f"/runs/{run_id}/evidence-pack", params={"download": "true"})
    assert download.headers["content-disposition"] == (
        f'attachment; filename="origin-run-{run_id}.json"'
    )
    assert download.json()["run"]["id"] == str(run_id)
    assert (await client.get(f"/runs/{uuid.uuid4()}/evidence-pack")).status_code == 404


async def test_rejected_candidates_come_with_how_they_were_judged(
    client: httpx.AsyncClient, db_engine: AsyncEngine, seed_run: SeedRun, tmp_path: Path
) -> None:
    run_id = await seed_run()
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    html = b"<html><title>Just a moment...</title><script>alert(1)</script></html>"
    blob = await blobs.put(html, "text/html")
    async with make_sessionmaker(db_engine).begin() as session:
        call = ProviderCall(
            run_id=run_id, provider="lens", request_hash="f" * 64, status=ProviderCallStatus.OK
        )
        session.add(call)
        await session.flush()
        page = Artefact(
            kind=ArtefactKind.PAGE_HTML,
            sha256=blob.sha256,
            storage_key=blob.key,
            content_type="text/html",
            byte_size=blob.byte_size,
            source_url="https://wall.example/story",
            http_status=403,
        )
        session.add(page)
        await session.flush()
        session.add_all(
            [
                Candidate(
                    run_id=run_id,
                    provider_call_id=call.id,
                    provider="lens",
                    page_url="https://www.google.com/goto?url=abc",
                    provider_rank=2,
                    status=CandidateStatus.FETCH_FAILED,
                    reject_reason="page HTTP 403",
                    raw={"source": "Wall News", "title": "A story"},
                    fetch_info={
                        "page": {"status": 403, "final_url": "https://wall.example/story"},
                        "images": [],
                        "verdict": "page HTTP 403",
                    },
                    page_artefact_id=page.id,
                ),
                Candidate(
                    run_id=run_id,
                    provider_call_id=call.id,
                    provider="lens",
                    page_url="https://ok.example/",
                    provider_rank=1,
                    status=CandidateStatus.VERIFIED,
                ),
                Candidate(
                    run_id=run_id,
                    provider_call_id=call.id,
                    provider="lens",
                    page_url="https://late.example/",
                    provider_rank=51,
                    status=CandidateStatus.PENDING,
                    reject_reason="not checked: beyond the top 50 hits",
                    raw={"source": "Late News", "title": "Ranked 51st"},
                ),
            ]
        )

    body = (await client.get(f"/runs/{run_id}/candidates")).json()
    assert body["counts"]["verified"] == 1 and body["counts"]["fetch_failed"] == 1
    assert len(body["rejected"]) == 1  # a sighting is not a rejection, nor is an unchecked hit
    assert body["counts"]["pending"] == 1
    assert body["check_limit"] == 50
    [unchecked] = body["unchecked"]
    assert unchecked["rank"] == 51 and unchecked["source"] == "Late News"
    assert unchecked["reason"] == "not checked: beyond the top 50 hits"
    rejected = body["rejected"][0]
    assert rejected["rank"] == 2 and rejected["source"] == "Wall News"
    assert rejected["status"] == "fetch_failed" and rejected["reason"] == "page HTTP 403"
    assert rejected["fetch_info"]["page"]["final_url"] == "https://wall.example/story"

    stored = await client.get(rejected["page_local"])
    assert stored.status_code == 200
    assert stored.content == html
    # Hostile HTML is served as inert text, never as a page the browser would run.
    assert stored.headers["content-type"].startswith("text/plain")
    assert stored.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in stored.headers["content-security-policy"]


async def test_candidate_without_a_stored_page_is_404(
    client: httpx.AsyncClient, db_engine: AsyncEngine, seed_run: SeedRun
) -> None:
    run_id = await seed_run()
    async with make_sessionmaker(db_engine).begin() as session:
        call = ProviderCall(
            run_id=run_id, provider="lens", request_hash="d" * 64, status=ProviderCallStatus.OK
        )
        session.add(call)
        await session.flush()
        candidate = Candidate(
            run_id=run_id,
            provider_call_id=call.id,
            provider="lens",
            page_url="https://x.example/",
            status=CandidateStatus.UNRELATED,
        )
        session.add(candidate)
        await session.flush()
        candidate_id = candidate.id
    assert (await client.get(f"/candidates/{candidate_id}/page")).status_code == 404
    assert (await client.get(f"/runs/{uuid.uuid4()}/candidates")).status_code == 404
