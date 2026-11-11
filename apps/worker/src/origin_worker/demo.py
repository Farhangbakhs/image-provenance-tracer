"""Demo mode: seed three investigations by running the real pipeline over a synthetic web.

    python -m origin_worker.demo seed             # replay recorded model answers (no keys)
    python -m origin_worker.demo seed --record    # call the real model once and record it
    python -m origin_worker.demo seed --fresh     # re-run every case (new runs; old ones kept)

What is synthetic, and labelled as such: the web pages and their `.example` domains, archive
dates, and the reverse-image index (`demo-index`), all declared in fixtures/demo/cases.json.
What is real: every stage that runs over them. Images are fetched through the hardened fetcher
(from an in-memory transport instead of the internet), fingerprinted, embedded, matched, dated,
clustered, read for claims and graded exactly as in a live trace. Claims and narratives come
from a real model: recorded once with --record, replayed afterwards, so demo mode needs no keys.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageDraw, ImageOps
from redis.asyncio import Redis
from sqlalchemy import select

from origin_core.db.models import Case, Run, Sighting
from origin_core.db.session import make_engine, make_sessionmaker
from origin_core.enums import RunStatus
from origin_core.fetch import Fetcher
from origin_core.ingest.service import IngestLimits, ingest_upload
from origin_core.llm.gemini import GeminiProvider
from origin_core.llm.registry import LLMSetup
from origin_core.llm.runner import LLMRunner
from origin_core.logging import configure_logging
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.runner import PipelineRunner
from origin_core.providers.base import AssetRef, CandidateHit, RawResponse
from origin_core.providers.fixtures import FixtureStore
from origin_core.providers.registry import ProviderSetup
from origin_core.providers.runner import ProviderRunner, RetryPolicy
from origin_core.settings import ProviderMode, Settings, get_settings
from origin_core.storage import make_blob_store
from origin_worker.embedding import SSCDEmbedder, ensure_weights
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.stages import TraceServices, build_stages

DEMO_MODEL = "gemini-3.5-flash-lite"
# The demo web is served from memory; nothing is sent to this address. It must still look like a
# global address, because the fetcher refuses private and reserved ones (TEST-NET included).
DEMO_IP = "93.184.216.34"


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "fixtures" / "demo" / "cases.json").exists():
            return parent
    return Path.cwd()


class DemoIndex:
    """Stands in for a reverse-image engine in demo mode. Synthetic, and named so."""

    name: str = "demo-index"
    quota_key: str = "demo-index"
    unit_cost: int = 0
    requires_public_url: bool = False
    recipients: tuple[str, ...] = ("nobody: the demo index is local and synthetic",)

    def __init__(self, case_key: str, hits: list[dict[str, Any]]) -> None:
        self._case = case_key
        self._body = json.dumps(hits).encode()

    def params(self) -> dict[str, Any]:
        return {"case": self._case}

    async def fetch(self, subject: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        return RawResponse(self._body)

    def parse(self, body: bytes) -> list[CandidateHit]:
        return [CandidateHit(**hit) for hit in json.loads(body)]


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


def edited(original: bytes, edit: str) -> bytes:
    if edit in ("none", "original_bytes"):
        return original
    with Image.open(io.BytesIO(original)) as opened:
        image = opened.convert("RGB")
    w, h = image.size
    if edit == "resize":
        return _jpeg(image.resize((w * 3 // 4, h * 3 // 4)))
    if edit == "mirror":
        return _jpeg(ImageOps.mirror(image))
    if edit == "crop_caption":
        crop = image.crop((int(w * 0.1), int(h * 0.05), int(w * 0.9), int(h * 0.85)))
        ImageDraw.Draw(crop).rectangle(
            (0, int(crop.height * 0.82), crop.width, crop.height), fill=(0, 0, 0)
        )
        return _jpeg(crop)
    raise ValueError(f"unknown edit {edit!r}")


def page_html(page: dict[str, Any], image_url: str) -> bytes:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{page["title"]}</title>
<meta property="og:title" content="{page["title"]}">
<meta property="og:image" content="{image_url}">
<meta property="article:published_time" content="{page["published"]}">
</head><body><article><h1>{page["title"]}</h1>
<figure><img src="{urlsplit(image_url).path}" alt="Photograph">
<figcaption>{page["caption"]}</figcaption></figure>
<p>{page["body"]}</p>
</article></body></html>""".encode()


@dataclass
class DemoWeb:
    responses: dict[tuple[str, str], tuple[str, bytes]]
    archive: dict[str, str]

    def serve(self, request: httpx.Request) -> httpx.Response:
        found = self.responses.get((request.headers["host"], request.url.path))
        if found is None:
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": found[0]}, content=found[1])

    def wayback(self, request: httpx.Request) -> httpx.Response:
        url = request.url.params.get("url", "")
        stamp = self.archive.get(url)
        if not stamp:
            return httpx.Response(200, json=[])
        rows = [
            ["timestamp", "original", "statuscode", "mimetype", "digest"],
            [stamp, url, "200", "text/html", "DEMO"],
        ]
        return httpx.Response(200, json=rows)


def build_web(case: dict[str, Any], root: Path, query: bytes) -> DemoWeb:
    responses: dict[tuple[str, str], tuple[str, bytes]] = {}
    archive: dict[str, str] = {}
    for page in case["pages"]:
        parts = urlsplit(str(page["url"]))
        host = parts.hostname or ""
        image_url = f"https://{host}{page['image']['path']}"
        responses[(host, parts.path)] = ("text/html; charset=utf-8", page_html(page, image_url))
        responses[(host, page["image"]["path"])] = (
            "image/jpeg",
            edited(query, page["image"]["edit"]),
        )
        archive[page["url"]] = page["archived"]
    for direct in case.get("direct_images", []):
        parts = urlsplit(str(direct["url"]))
        responses[(parts.hostname or "", parts.path)] = (
            "image/jpeg",
            edited(query, direct["edit"]),
        )
        archive[direct["url"]] = direct["archived"]
    for url, path in case.get("unrelated", {}).items():
        parts = urlsplit(str(url))
        responses[(parts.hostname or "", parts.path)] = ("image/jpeg", (root / path).read_bytes())
    return DemoWeb(responses, archive)


async def seed(settings: Settings, *, record: bool, fresh: bool = False) -> list[tuple[str, str]]:
    root = _repo_root()
    spec = json.loads((root / "fixtures" / "demo" / "cases.json").read_text(encoding="utf-8"))
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url)
    blobs = make_blob_store(settings)
    await blobs.ensure_ready()
    embedder = SSCDEmbedder(await ensure_weights(settings.models_dir))
    fixtures = FixtureStore((root / "fixtures" / "recordings", root / "fixtures" / "synthetic"))

    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    if record and not key:
        raise SystemExit("--record needs GEMINI_API_KEY")
    llm_mode = ProviderMode.RECORD if record else ProviderMode.REPLAY
    llm_http = httpx.AsyncClient()
    llm = LLMSetup(
        GeminiProvider(key or "replay-mode-no-key", DEMO_MODEL), secrets=(key,) if key else ()
    )
    llm_runner = LLMRunner(
        sessions=sessions,
        blobs=blobs,
        http=llm_http,
        mode=llm_mode,
        fixtures=fixtures,
        redact_secrets=llm.secrets,
    )

    seeded: list[tuple[str, str]] = []
    try:
        for case in spec["cases"]:
            async with sessions() as session:
                existing = (
                    await session.execute(select(Case).where(Case.title == case["title"]))
                ).scalar_one_or_none()
                done = (
                    existing is not None
                    and (
                        await session.execute(
                            select(Sighting.id)
                            .join(Run, Run.id == Sighting.run_id)
                            .where(Run.case_id == existing.id, Run.status == RunStatus.SUCCEEDED)
                            .limit(1)
                        )
                    ).first()
                    is not None
                )
            if done and not fresh:
                print(f"skip  {case['title']} (already seeded)")
                continue
            query = (root / case["query"]).read_bytes()
            web = build_web(case, root, query)

            async def resolve(host: str, port: int) -> list[str]:
                return [DEMO_IP]

            fetcher = Fetcher(resolver=resolve, transport=httpx.MockTransport(web.serve))
            runner = ProviderRunner(
                sessions=sessions,
                blobs=blobs,
                http=httpx.AsyncClient(transport=httpx.MockTransport(web.wayback)),
                policies={},
                retry=RetryPolicy(attempts=1),
            )
            stages = build_stages(
                blobs=blobs,
                embedder=embedder,
                trace=TraceServices(
                    providers=ProviderSetup(adapters=[DemoIndex(case["key"], case["hits"])]),
                    runner=runner,
                    fetcher=fetcher,
                    thresholds=load_thresholds(),
                    max_pixels=settings.upload_max_pixels,
                    exiftool=settings.exiftool_path,
                    llm=llm,
                    llm_runner=llm_runner,
                ),
            )
            async with sessions.begin() as session:
                row = existing or Case(title=case["title"], notes=case["notes"], owner="demo")
                session.add(row)
                await session.flush()
                # Re-seeding an incomplete demo case adds a new run; earlier runs stay as history.
                result = await ingest_upload(
                    session,
                    blobs,
                    case_id=row.id,
                    data=query,
                    filename=Path(case["query"]).name,
                    limits=IngestLimits(settings.upload_max_bytes, settings.upload_max_pixels),
                    exiftool=settings.exiftool_path,
                )
                run = Run(case_id=row.id, asset_id=result.asset.id, providers=["demo-index"])
                session.add(run)
                await session.flush()
                run_id = run.id
            status = await PipelineRunner(
                sessions=sessions, events=RunEventBus(redis), stages=stages
            ).execute(run_id)
            await fetcher.aclose()
            print(f"{status.value:9} {case['title']} -> run {run_id}")
            if status is not RunStatus.SUCCEEDED:
                raise SystemExit(f"demo case {case['key']} did not complete")
            seeded.append((case["key"], str(run_id)))
    finally:
        await llm_http.aclose()
        await redis.aclose()
        await engine.dispose()
    return seeded


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="origin_worker.demo")
    sub = parser.add_subparsers(dest="cmd", required=True)
    seed_cmd = sub.add_parser("seed", help="seed the demo investigations")
    seed_cmd.add_argument("--record", action="store_true", help="call the real model and record it")
    seed_cmd.add_argument(
        "--fresh", action="store_true", help="add a new run even to cases already seeded"
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    asyncio.run(seed(settings, record=args.record, fresh=args.fresh))


if __name__ == "__main__":
    main()
