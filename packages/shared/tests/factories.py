"""Minimal valid rows for database tests."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from origin_core.db.models import Artefact, Asset, Candidate, Case, ProviderCall, Run, Sighting
from origin_core.enums import ArtefactKind, C2PAState, MatchClass, ProviderCallStatus


@dataclass
class Graph:
    case: Case
    asset: Asset
    run: Run
    sighting: Sighting


def _artefact(kind: ArtefactKind, sha: str) -> Artefact:
    return Artefact(
        kind=kind, sha256=sha, storage_key=f"sha256/{sha}", content_type="image/jpeg", byte_size=1
    )


async def make_graph(session: AsyncSession) -> Graph:
    case = Case(title="test case")
    original = _artefact(ArtefactKind.ORIGINAL, "a" * 64)
    fetched = _artefact(ArtefactKind.FETCHED_IMAGE, "b" * 64)
    session.add_all([case, original, fetched])
    await session.flush()

    asset = Asset(
        case_id=case.id,
        original_artefact_id=original.id,
        content_type="image/jpeg",
        width=10,
        height=10,
        sha256=original.sha256,
        phash="0" * 16,
        dhash="0" * 16,
        pdq="0" * 64,
        pdq_quality=100,
        c2pa_state=C2PAState.NONE,
    )
    session.add(asset)
    await session.flush()

    run = Run(case_id=case.id, asset_id=asset.id)
    session.add(run)
    await session.flush()

    call = ProviderCall(
        run_id=run.id, provider="fixture", request_hash="c" * 64, status=ProviderCallStatus.REPLAYED
    )
    session.add(call)
    await session.flush()

    candidate = Candidate(
        run_id=run.id,
        provider_call_id=call.id,
        provider="fixture",
        image_url="https://example.org/a.jpg",
    )
    session.add(candidate)
    await session.flush()

    sighting = Sighting(
        run_id=run.id,
        candidate_id=candidate.id,
        image_artefact_id=fetched.id,
        image_url=candidate.image_url or "",
        match_class=MatchClass.EXACT,
        threshold_version="v1",
    )
    session.add(sighting)
    await session.flush()
    return Graph(case=case, asset=asset, run=run, sighting=sighting)
