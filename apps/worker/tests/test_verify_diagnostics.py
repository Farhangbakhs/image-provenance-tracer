"""A rejected candidate keeps what ORIGIN fetched, so its verdict can be explained afterwards."""

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

from origin_core.db.models import Artefact, Asset, Candidate, ProviderCall, Run
from origin_core.db.session import make_sessionmaker
from origin_core.enums import ArtefactKind, CandidateStatus, ProviderCallStatus
from origin_core.fetch import Fetcher
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.runner import StageContext
from origin_core.storage import FilesystemBlobStore
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.trace import VerifyStage

pytestmark = [pytest.mark.db, pytest.mark.redis]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"

NO_IMAGE_PAGE = (
    b"<html><head><title>Hello</title></head><body><p>No pictures here.</p></body></html>"
)
WALL_PAGE = (
    b"<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
)


async def _verify(
    db_engine: AsyncEngine,
    redis: Redis,
    seed_run: SeedRun,
    tmp_path: Path,
    urls: list[str],
    serve: Any,
) -> tuple[uuid.UUID, FilesystemBlobStore]:
    blobs = FilesystemBlobStore(tmp_path)
    run_id = await seed_run(image=(FIXTURES / "no-manifest.jpg").read_bytes(), blobs=blobs)
    sessions = make_sessionmaker(db_engine)
    async with sessions.begin() as session:
        run = await session.get_one(Run, run_id)
        await session.execute(
            update(Asset).where(Asset.id == run.asset_id).values(embedding=[0.0] * 512)
        )
        call = ProviderCall(
            run_id=run_id,
            provider="scripted",
            request_hash=uuid.uuid4().hex * 2,
            params={},
            status=ProviderCallStatus.OK,
        )
        session.add(call)
        await session.flush()
        for rank, url in enumerate(urls, start=1):
            session.add(
                Candidate(
                    run_id=run_id,
                    provider_call_id=call.id,
                    provider="scripted",
                    page_url=url,
                    provider_rank=rank,
                    raw={"source": "Example News"},
                )
            )

    async def resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    fetcher = Fetcher(resolver=resolve, transport=httpx.MockTransport(serve))
    stage = VerifyStage(
        fetcher=fetcher,
        blobs=blobs,
        embedder=cast(Any, None),  # no page has an image, so none is embedded
        thresholds=load_thresholds(),
        max_pixels=50_000_000,
    )
    await stage.run(StageContext(run_id=run_id, sessions=sessions, events=RunEventBus(redis)))
    await fetcher.aclose()
    return run_id, blobs


async def _rows(db_engine: AsyncEngine, run_id: uuid.UUID) -> dict[int, Candidate]:
    async with make_sessionmaker(db_engine)() as session:
        return {
            c.provider_rank: c
            for c in (
                await session.execute(select(Candidate).where(Candidate.run_id == run_id))
            ).scalars()
            if c.provider_rank is not None
        }


async def test_a_page_without_images_says_what_it_was(
    db_engine: AsyncEngine, redis: Redis, seed_run: SeedRun, tmp_path: Path
) -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "https://b.example/new"})
        if request.headers["host"] == "wall.example":
            return httpx.Response(403, headers={"content-type": "text/html"}, content=WALL_PAGE)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=NO_IMAGE_PAGE)

    run_id, blobs = await _verify(
        db_engine,
        redis,
        seed_run,
        tmp_path,
        ["https://a.example/old", "https://wall.example/story"],
        serve,
    )
    rows = await _rows(db_engine, run_id)

    empty = rows[1]
    assert empty.status is CandidateStatus.UNRELATED
    assert empty.reject_reason == (
        f"no image on the page (HTTP 200, text/html, {len(NO_IMAGE_PAGE):,} bytes)"
    )
    assert empty.fetch_info is not None
    page = empty.fetch_info["page"]
    assert page["status"] == 200
    assert page["final_url"] == "https://b.example/new"  # the redirect was followed and recorded
    assert page["redirects"] == 1
    assert page["content_type"] == "text/html"
    assert page["bytes"] == len(NO_IMAGE_PAGE)
    assert page["images_found"] == 0
    assert page["title"] == "Hello"
    assert empty.fetch_info["images"] == []

    walled = rows[2]
    assert walled.status is CandidateStatus.FETCH_FAILED
    assert walled.reject_reason == "page HTTP 403"
    assert walled.fetch_info is not None and walled.fetch_info["page"]["status"] == 403

    # Both pages were kept, content-addressed like every other artefact.
    async with make_sessionmaker(db_engine)() as session:
        for candidate, body in ((empty, NO_IMAGE_PAGE), (walled, WALL_PAGE)):
            assert candidate.page_artefact_id is not None
            artefact = await session.get_one(Artefact, candidate.page_artefact_id)
            assert artefact.kind is ArtefactKind.PAGE_HTML
            assert artefact.http_status == (200 if body == NO_IMAGE_PAGE else 403)
            assert await blobs.get(artefact.storage_key) == body


async def test_an_unreachable_page_records_the_error(
    db_engine: AsyncEngine, redis: Redis, seed_run: SeedRun, tmp_path: Path
) -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    run_id, _ = await _verify(
        db_engine, redis, seed_run, tmp_path, ["https://down.example/"], serve
    )
    candidate = (await _rows(db_engine, run_id))[1]

    assert candidate.status is CandidateStatus.FETCH_FAILED
    assert candidate.reject_reason is not None
    assert candidate.reject_reason.startswith("page fetch failed")
    assert candidate.page_artefact_id is None  # nothing was fetched, so nothing is kept
    assert candidate.fetch_info is not None
    assert candidate.fetch_info["page"]["status"] is None
    assert candidate.fetch_info["page"]["error"] == candidate.reject_reason
