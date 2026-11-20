"""The image Lens says it matched is found on a crowded page, using the size Lens reports."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import SeedRun

from origin_core.db.models import Asset, Candidate, ProviderCall, Run, Sighting
from origin_core.db.session import make_sessionmaker
from origin_core.enums import CandidateStatus, MatchClass, ProviderCallStatus
from origin_core.fetch import Fetcher
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.runner import StageContext
from origin_core.storage import FilesystemBlobStore
from origin_worker.embedding import SSCDEmbedder
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.trace import VerifyStage

pytestmark = [pytest.mark.db, pytest.mark.redis]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"


def _page(target: int) -> bytes:
    """Twenty gallery images; only number `target` is the one declared 600x400."""
    imgs = [
        f'<img src="/img/{i}.jpg" '
        + ('width="600" height="400">' if i == target else 'width="300" height="300">')
        for i in range(20)
    ]
    return (
        "<html><head><title>Gallery</title></head><body>" + "".join(imgs) + "</body></html>"
    ).encode()


async def test_the_matched_size_finds_the_image_the_cap_would_lose(
    db_engine: AsyncEngine,
    redis: Redis,
    seed_run: SeedRun,
    tmp_path: Path,
    embedder: SSCDEmbedder,
) -> None:
    photo = (FIXTURES / "no-manifest.jpg").read_bytes()
    blobs = FilesystemBlobStore(tmp_path)
    run_id = await seed_run(image=photo, blobs=blobs)
    sessions = make_sessionmaker(db_engine)
    tag = uuid.uuid4().hex[:8]
    host = f"gallery-{tag}.example"
    async with sessions.begin() as session:
        run = await session.get_one(Run, run_id)
        await session.execute(
            update(Asset).where(Asset.id == run.asset_id).values(embedding=[0.0] * 512)
        )
        call = ProviderCall(
            run_id=run_id,
            provider="lens",
            request_hash=tag * 8,
            params={},
            status=ProviderCallStatus.OK,
        )
        session.add(call)
        await session.flush()
        # Same page, twice: Lens reported the matched image's size for the first hit only.
        for rank, path, raw in (
            (1, "/with-size", {"actual_image_width": 600, "actual_image_height": 400}),
            (2, "/no-size", {}),
        ):
            session.add(
                Candidate(
                    run_id=run_id,
                    provider_call_id=call.id,
                    provider="lens",
                    page_url=f"https://{host}{path}",
                    provider_rank=rank,
                    raw=raw,
                )
            )

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/with-size", "/no-size"):
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=_page(target=17)
            )
        if request.url.path == "/img/17.jpg":
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=photo)
        return httpx.Response(404)

    async def resolve(h: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    fetcher = Fetcher(resolver=resolve, transport=httpx.MockTransport(serve))
    stage = VerifyStage(
        fetcher=fetcher,
        blobs=blobs,
        embedder=embedder,
        thresholds=load_thresholds(),
        max_pixels=50_000_000,
    )
    await stage.run(StageContext(run_id=run_id, sessions=sessions, events=RunEventBus(redis)))
    await fetcher.aclose()

    async with sessions() as session:
        rows = {
            c.provider_rank: c
            for c in (
                await session.execute(select(Candidate).where(Candidate.run_id == run_id))
            ).scalars()
        }
        sighting = (
            await session.execute(select(Sighting).where(Sighting.run_id == run_id))
        ).scalar_one()

    # With the size, the 18th image on the page is tried early, found, and kept as the evidence.
    assert rows[1].status is CandidateStatus.VERIFIED
    assert sighting.image_url == f"https://{host}/img/17.jpg"
    assert sighting.match_class is MatchClass.EXACT
    assert rows[1].fetch_info is not None
    assert rows[1].fetch_info["matched_size"] == [600, 400]
    assert len(rows[1].fetch_info["images"]) <= 12

    # Without it, the same page loses that image behind the twelve-image cap.
    assert rows[2].status is not CandidateStatus.VERIFIED
    assert rows[2].fetch_info is not None and rows[2].fetch_info["matched_size"] is None
