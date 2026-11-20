"""Lens links are Google redirects. Sightings keep the publisher URL; Google gates are blocked."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import ScriptedProvider, SeedRun

from origin_core.db.models import Artefact, Candidate, Sighting, Source
from origin_core.db.session import make_sessionmaker
from origin_core.enums import CandidateStatus, RunStatus
from origin_core.fetch import Fetcher
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.runner import PipelineRunner
from origin_core.providers import wayback
from origin_core.providers.registry import ProviderSetup
from origin_core.providers.runner import ProviderRunner, RetryPolicy
from origin_core.storage import FilesystemBlobStore
from origin_worker.embedding import SSCDEmbedder
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.stages import TraceServices, build_stages

pytestmark = [pytest.mark.db, pytest.mark.redis]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"
HTML = {"content-type": "text/html"}
GOTO = "https://www.google.com/goto?url="


def _publisher_page(host: str) -> bytes:
    return (
        "<html><head><title>Floods</title>"
        f'<meta property="og:image" content="https://{host}/media/photo.jpg">'
        "</head><body></body></html>"
    ).encode()


def _redirect(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": location})


async def test_sightings_keep_the_publisher_url_and_google_gates_are_blocked(
    db_engine: AsyncEngine,
    redis: Redis,
    tmp_path: Path,
    embedder: SSCDEmbedder,
    seed_run: SeedRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wayback, "_PACER", wayback._Pacer(0))  # pyright: ignore[reportPrivateUsage]
    photo = (FIXTURES / "no-manifest.jpg").read_bytes()
    # A host no other test uses: the provider cache is shared through the database.
    pub = f"pub-{uuid.uuid4().hex[:8]}.example"

    def serve(request: httpx.Request) -> httpx.Response:
        host, path = request.headers["host"], request.url.path
        if host == "www.google.com" and path == "/goto":
            return {
                "ok": _redirect(f"https://{pub}/story"),
                "sorry": _redirect("https://www.google.com/sorry/index?continue=x"),
                "consent": _redirect("https://consent.google.com/ml?continue=x"),
                "notice": httpx.Response(
                    200, headers=HTML, content=b"<html><title>Redirect Notice</title></html>"
                ),
                "site": _redirect("https://sites.google.com/view/r"),
            }[request.url.params["url"]]
        if host == "www.google.com" and path.startswith("/sorry"):
            return httpx.Response(429, headers=HTML, content=b"<html>unusual traffic</html>")
        if host == "consent.google.com":
            return httpx.Response(200, headers=HTML, content=b"<html>Before you continue</html>")
        if host == "sites.google.com":
            return httpx.Response(
                200, headers=HTML, content=b"<html><body>No picture</body></html>"
            )
        if (host, path) == (pub, "/story"):
            return httpx.Response(200, headers=HTML, content=_publisher_page(pub))
        if (host, path) == (pub, "/media/photo.jpg"):
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=photo)
        return httpx.Response(404)

    cdx_urls: list[str] = []

    def cdx(request: httpx.Request) -> httpx.Response:
        cdx_urls.append(request.url.params.get("url", ""))
        return httpx.Response(200, json=[])

    async def resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    blobs = FilesystemBlobStore(tmp_path)
    sessions = make_sessionmaker(db_engine)
    provider = ScriptedProvider(
        [
            {"page_url": f"{GOTO}ok", "rank": 1},
            {"page_url": f"{GOTO}sorry", "rank": 2},
            {"page_url": f"{GOTO}consent", "rank": 3},
            {"page_url": f"{GOTO}notice", "rank": 4},
            {"page_url": f"{GOTO}site", "rank": 5},
        ],
        name="scripted-google",
    )
    fetcher = Fetcher(resolver=resolve, transport=httpx.MockTransport(serve))
    stages = build_stages(
        blobs=blobs,
        embedder=embedder,
        trace=TraceServices(
            providers=ProviderSetup(adapters=[provider], unavailable={}),
            runner=ProviderRunner(
                sessions=sessions,
                blobs=blobs,
                http=httpx.AsyncClient(transport=httpx.MockTransport(cdx)),
                policies={},
                retry=RetryPolicy(attempts=1),
            ),
            fetcher=fetcher,
            thresholds=load_thresholds(),
            max_pixels=50_000_000,
            exiftool="exiftool",
        ),
    )
    run_id = await seed_run(image=photo, blobs=blobs)
    status = await PipelineRunner(
        sessions=sessions, events=RunEventBus(redis), stages=stages
    ).execute(run_id)
    await fetcher.aclose()
    assert status is RunStatus.SUCCEEDED

    async with sessions() as session:
        by_rank = {
            c.provider_rank: c
            for c in (
                await session.execute(select(Candidate).where(Candidate.run_id == run_id))
            ).scalars()
        }
        sighting = (
            await session.execute(select(Sighting).where(Sighting.run_id == run_id))
        ).scalar_one()
        source = await session.get_one(Source, sighting.source_id)
        assert by_rank[2].page_artefact_id is not None
        kept = await session.get_one(Artefact, by_rank[2].page_artefact_id)

    # The verified copy is attributed to the publisher; the Google link is kept as provenance.
    assert by_rank[1].status is CandidateStatus.VERIFIED
    assert sighting.page_url == f"https://{pub}/story"
    assert sighting.provider_url == f"{GOTO}ok"
    assert source.key == pub
    # The archive was asked about the publisher's page, never about the redirect.
    assert f"https://{pub}/story" in cdx_urls
    assert not any("google.com" in url for url in cdx_urls)

    # Google's own captcha, consent and redirect-notice pages are named, not "no image".
    for rank, where in (
        (2, "www.google.com/sorry/index, HTTP 429"),
        (3, "consent.google.com/ml, HTTP 200"),
        (4, "www.google.com/goto, HTTP 200"),
    ):
        blocked = by_rank[rank]
        assert blocked.status is CandidateStatus.BLOCKED
        assert blocked.reject_reason == f"blocked by Google redirect ({where})"
    assert by_rank[2].fetch_info is not None
    assert by_rank[2].fetch_info["page"]["final_url"].startswith("https://www.google.com/sorry")
    assert kept.http_status == 429  # what Google answered is kept as evidence

    # A publisher that lives on a Google host is judged on its page, not blocked.
    assert by_rank[5].status is CandidateStatus.UNRELATED
    assert (by_rank[5].reject_reason or "").startswith("no image on the page")
