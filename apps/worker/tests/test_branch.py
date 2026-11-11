"""The miscaptioned-image case: one photo, two stories, and where the second one starts.

Three pages carry copies of the same photograph. The two earliest (proven by archive captures)
say it shows a flood in Valencia; the latest, a mirrored copy, says it shows a hurricane in
Florida. The full pipeline (ingest, discover, verify, date, branch) must produce two narratives:
the Valencia root, and a Florida branch that diverges at the latest page. The language model is a
scripted test double; everything else is real.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageOps
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import ScriptedProvider, SeedRun

from origin_core.db.models import Claim, Narrative, NarrativeClaim, Sighting, Variant, VariantEdge
from origin_core.db.session import make_sessionmaker
from origin_core.enums import RunStatus
from origin_core.fetch import Fetcher
from origin_core.llm.base import Prompt, RawReply
from origin_core.llm.prompts import claim as claim_prompt
from origin_core.llm.registry import LLMSetup
from origin_core.llm.runner import LLMRunner
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

PHOTO = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa" / "no-manifest.jpg"

PAGES = {
    "first.example": (
        "Floods sweep through Valencia",
        "Floodwater fills a street in Valencia, Spain, on 29 October 2024 after record rainfall.",
        "20241030080000",
    ),
    "second.example": (
        "Valencia counts the cost",
        "This photo shows the flooded street in Valencia on 29 October 2024, residents said.",
        "20241105120000",
    ),
    "third.example": (
        "Hurricane devastation",
        "Shocking image of Hurricane Milton flooding a street in Tampa, Florida this week.",
        None,
    ),
}


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _page(domain: str, title: str, caption: str) -> bytes:
    return f"""<html><head><title>{title}</title>
    <meta property="og:image" content="https://{domain}/photo.jpg"></head>
    <body><article><h1>{title}</h1>
    <figure><img src="/photo.jpg" alt="Flooded street"><figcaption>{caption}</figcaption></figure>
    <p>{caption} Emergency services worked through the night as residents waited for news.
    Officials said the clean-up would take weeks and warned people to stay away from the area.</p>
    </article></body></html>""".encode()


class ScriptedLLM:
    """Answers the claim prompt from the page it was shown, and the narrative prompt by grouping
    Valencia claims together and Florida apart, as a careful model would."""

    name: str = "scripted"
    model: str = "scripted-1"

    async def complete(self, prompt: Prompt, client: httpx.AsyncClient) -> RawReply:
        if prompt.version == claim_prompt.VERSION:
            florida = "Florida" in prompt.user
            # Copy the quote from the text actually given, as the rules require.
            marker = "Text: " if "Text: " in prompt.user else "Caption: "
            quote = prompt.user.split(marker, 1)[1].split(".")[0] + "."
            answer = {
                "has_claim": True,
                "event": "hurricane flooding" if florida else "flood",
                "place": "Tampa, Florida" if florida else "Valencia, Spain",
                "date_text": "this week" if florida else "29 October 2024",
                "date_iso": None if florida else "2024-10-29",
                "actor_role": "residents",
                "stance": "asserts",
                "quote": quote,
                "language": "en",
                "translation": None,
            }
        else:
            claims = json.loads(prompt.user.split(">>>\n", 1)[1].split("\n<<<END", 1)[0])
            valencia = [c["id"] for c in claims if "Valencia" in (c["place"] or "")]
            florida = [c["id"] for c in claims if c["id"] not in valencia]
            answer = {
                "narratives": [
                    {
                        "label": "Flood in Valencia, Oct 2024",
                        "summary": "Valencia flood.",
                        "claim_ids": valencia,
                        "contradicts_earliest": False,
                    },
                    {
                        "label": "Hurricane in Florida",
                        "summary": "Claimed to show Hurricane Milton in Tampa.",
                        "claim_ids": florida,
                        "contradicts_earliest": True,
                        "contradiction": "place",
                        "reason": "places the photo in Tampa, Florida instead of Valencia, Spain",
                    },
                ]
            }
        return RawReply(json.dumps({"text": json.dumps(answer)}).encode())

    def text(self, body: bytes) -> str:
        return str(json.loads(body)["text"])


async def test_miscaptioned_image_branches_at_the_first_false_caption(
    db_engine: AsyncEngine,
    redis: Redis,
    tmp_path: Path,
    embedder: SSCDEmbedder,
    seed_run: SeedRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wayback, "_PACER", wayback._Pacer(0))  # pyright: ignore[reportPrivateUsage]
    photo_bytes = PHOTO.read_bytes()
    with Image.open(io.BytesIO(photo_bytes)) as opened:
        photo = opened.convert("RGB")
    images = {
        "first.example": _jpeg(photo),
        "second.example": _jpeg(photo.resize((photo.width * 3 // 4, photo.height * 3 // 4))),
        "third.example": _jpeg(ImageOps.mirror(photo)),
    }

    def serve(request: httpx.Request) -> httpx.Response:
        host, path = request.headers["host"], request.url.path
        if host in PAGES and path == "/story":
            title, caption, _ = PAGES[host]
            return httpx.Response(
                200, headers={"content-type": "text/html"}, content=_page(host, title, caption)
            )
        if host in images and path == "/photo.jpg":
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=images[host])
        return httpx.Response(404)

    def archive(request: httpx.Request) -> httpx.Response:
        url = request.url.params.get("url", "")
        host = url.split("/")[2] if "//" in url else ""
        stamp = PAGES.get(host, (None, None, None))[2]
        if stamp and url.endswith("/story"):
            return httpx.Response(
                200,
                json=[
                    ["timestamp", "original", "statuscode", "mimetype", "digest"],
                    [stamp, url, "200", "text/html", "D"],
                ],
            )
        return httpx.Response(200, json=[])

    async def resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    blobs = FilesystemBlobStore(tmp_path)
    sessions = make_sessionmaker(db_engine)
    fetcher = Fetcher(resolver=resolve, transport=httpx.MockTransport(serve))
    stages = build_stages(
        blobs=blobs,
        embedder=embedder,
        trace=TraceServices(
            providers=ProviderSetup(
                adapters=[
                    ScriptedProvider(
                        [
                            {"page_url": f"https://{d}/story", "rank": i}
                            for i, d in enumerate(PAGES, 1)
                        ],
                        name="scripted-branch",
                    )
                ]
            ),
            runner=ProviderRunner(
                sessions=sessions,
                blobs=blobs,
                http=httpx.AsyncClient(transport=httpx.MockTransport(archive)),
                policies={},
                retry=RetryPolicy(attempts=1),
            ),
            fetcher=fetcher,
            thresholds=load_thresholds(),
            max_pixels=50_000_000,
            exiftool="exiftool",
            llm=LLMSetup(ScriptedLLM()),
            llm_runner=LLMRunner(sessions=sessions, blobs=blobs, http=httpx.AsyncClient()),
        ),
    )
    run_id = await seed_run(image=photo_bytes, blobs=blobs)
    status = await PipelineRunner(
        sessions=sessions, events=RunEventBus(redis), stages=stages
    ).execute(run_id)
    assert status is RunStatus.SUCCEEDED
    await fetcher.aclose()

    async with sessions() as session:
        sightings = {
            s.page_url.split("/")[2]: s  # type: ignore[union-attr]
            for s in (
                await session.execute(select(Sighting).where(Sighting.run_id == run_id))
            ).scalars()
        }
        claims = list(
            (await session.execute(select(Claim).where(Claim.run_id == run_id))).scalars()
        )
        narratives = list(
            (await session.execute(select(Narrative).where(Narrative.run_id == run_id))).scalars()
        )
        members = {
            n.id: {
                c
                for c in (
                    await session.execute(
                        select(NarrativeClaim.claim_id).where(NarrativeClaim.narrative_id == n.id)
                    )
                ).scalars()
            }
            for n in narratives
        }
        variants = list(
            (await session.execute(select(Variant).where(Variant.run_id == run_id))).scalars()
        )
        edges = list(
            (
                await session.execute(select(VariantEdge).where(VariantEdge.run_id == run_id))
            ).scalars()
        )

    assert set(sightings) == set(PAGES)

    # Every claim cites its sighting and quotes the page verbatim.
    assert len(claims) == 3
    for claim in claims:
        sighting = next(s for s in sightings.values() if s.id == claim.sighting_id)
        assert sighting.extracted_text is not None
        assert sighting.extracted_text[claim.quote_start : claim.quote_end] == claim.quote
        assert (claim.llm_provider, claim.prompt_version) == ("scripted", claim_prompt.VERSION)

    # Two narratives: the Valencia root and the Florida branch that diverges at the third page.
    assert len(narratives) == 2
    root = next(n for n in narratives if n.parent_narrative_id is None)
    branch = next(n for n in narratives if n.parent_narrative_id is not None)
    assert branch.parent_narrative_id == root.id
    assert root.divergence_sighting_id == sightings["first.example"].id
    assert branch.divergence_sighting_id == sightings["third.example"].id
    assert branch.divergence_reason and "Florida" in branch.divergence_reason
    claim_of = {c.sighting_id: c.id for c in claims}
    assert members[root.id] == {
        claim_of[sightings["first.example"].id],
        claim_of[sightings["second.example"].id],
    }
    assert members[branch.id] == {claim_of[sightings["third.example"].id]}

    # Variants: the original and its resized copy are one variant; the mirror is an edit of it.
    assert len(variants) == 2
    assert [e.kind.value for e in edges] == ["mirror"]

    # Every sighting is graded, with an unassessed source at F and a rationale.
    for sighting in sightings.values():
        assert sighting.reliability == "F"
        assert sighting.credibility is not None and sighting.grade_rationale
    assert sightings["first.example"].credibility == 2  # same picture, archived once
