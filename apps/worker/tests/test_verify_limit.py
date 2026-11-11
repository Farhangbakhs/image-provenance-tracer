"""The verify stage checks only the best-ranked hits and marks the rest as not checked."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import SeedRun

from origin_core.db.models import Asset, Candidate, ProviderCall, Run
from origin_core.db.session import make_sessionmaker
from origin_core.enums import CandidateStatus, ProviderCallStatus
from origin_core.fetch import Fetcher
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.runner import StageContext
from origin_core.storage import FilesystemBlobStore
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.trace import VerifyStage

pytestmark = [pytest.mark.db, pytest.mark.redis]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"


async def test_only_the_top_hits_are_checked(
    db_engine: AsyncEngine, redis: Redis, seed_run: SeedRun, tmp_path: Path
) -> None:
    blobs = FilesystemBlobStore(tmp_path)
    run_id = await seed_run(image=(FIXTURES / "no-manifest.jpg").read_bytes(), blobs=blobs)
    sessions = make_sessionmaker(db_engine)
    tag = uuid.uuid4().hex[:8]
    async with sessions.begin() as session:
        run = await session.get_one(Run, run_id)
        await session.execute(
            update(Asset).where(Asset.id == run.asset_id).values(embedding=[0.0] * 512)
        )
        call = ProviderCall(
            run_id=run_id,
            provider="scripted",
            request_hash=tag * 8,
            params={},
            status=ProviderCallStatus.OK,
        )
        session.add(call)
        await session.flush()
        for rank in (3, 1, 2):
            session.add(
                Candidate(
                    run_id=run_id,
                    provider_call_id=call.id,
                    provider="scripted",
                    page_url=f"https://limit-{tag}.example/{rank}",
                    provider_rank=rank,
                )
            )

    async def resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    fetcher = Fetcher(
        resolver=resolve, transport=httpx.MockTransport(lambda r: httpx.Response(404))
    )
    stage = VerifyStage(
        fetcher=fetcher,
        blobs=blobs,
        embedder=cast(Any, None),  # no page loads, so no image is embedded
        thresholds=load_thresholds(),
        max_pixels=50_000_000,
        max_candidates=2,
    )
    result = await stage.run(
        StageContext(run_id=run_id, sessions=sessions, events=RunEventBus(redis))
    )
    await fetcher.aclose()

    assert result.counts["unchecked"] == 1 and result.counts["fetch_failed"] == 2
    assert "checked the top 2 of 3" in result.notes["verify"]
    async with sessions() as session:
        rows = {
            c.provider_rank: c
            for c in (
                await session.execute(select(Candidate).where(Candidate.run_id == run_id))
            ).scalars()
        }
    assert rows[1].status is CandidateStatus.FETCH_FAILED
    assert rows[2].status is CandidateStatus.FETCH_FAILED
    assert rows[3].status is CandidateStatus.PENDING
    assert rows[3].reject_reason == "not checked: beyond the top 2 hits"
