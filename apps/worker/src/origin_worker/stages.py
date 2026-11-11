"""Pipeline stages executed by the worker, in the order of origin_core.pipeline.registry.

Ingest is split across two processes on purpose. The API validates, stores, fingerprints and
reads metadata and Content Credentials at upload time, because those are fast and an upload
should be refused at the door. The SSCD embedding needs PyTorch and a 99 MB model, so it runs
here, as the pipeline's ingest stage, and the API never loads the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from origin_core.db.models import Artefact, Asset, Run
from origin_core.fetch import Fetcher
from origin_core.ingest.validate import decode_rgb
from origin_core.llm.registry import LLMSetup
from origin_core.llm.runner import LLMRunner
from origin_core.pipeline.runner import Stage, StageContext, StageResult
from origin_core.providers.registry import ProviderSetup
from origin_core.providers.runner import ProviderRunner
from origin_core.providers.telegram import TelegramIndex
from origin_core.storage import BlobStore
from origin_worker.branch import BranchStage
from origin_worker.embedding import SSCDEmbedder
from origin_worker.matching.thresholds import Thresholds
from origin_worker.telegram.collector import Collector
from origin_worker.telegram.sources import PhotoSource
from origin_worker.telegram.sweep import SweepStage
from origin_worker.trace import DateStage, DiscoverStage, VerifyStage


@dataclass
class IngestStage:
    """Complete the run's asset with its SSCD embedding. Idempotent: skips if already done."""

    blobs: BlobStore
    embedder: SSCDEmbedder
    name: str = "ingest"

    async def run(self, ctx: StageContext) -> StageResult:
        async with ctx.sessions() as session:
            row = (
                await session.execute(
                    select(Asset.id, Asset.embedding_model, Artefact.storage_key)
                    .join(Run, Run.asset_id == Asset.id)
                    .join(Artefact, Artefact.id == Asset.original_artefact_id)
                    .where(Run.id == ctx.run_id)
                )
            ).one()
        if row.embedding_model == self.embedder.spec.id:
            return StageResult(counts={"embeddings_reused": 1})

        data = await self.blobs.get(row.storage_key)
        vector = await self.embedder.embed(decode_rgb(data))
        async with ctx.sessions.begin() as session:
            asset = await session.get_one(Asset, row.id, with_for_update=True)
            asset.embedding = vector
            asset.embedding_model = self.embedder.spec.id
        await ctx.progress(self.name, embeddings_computed=1)
        return StageResult(counts={"embeddings_computed": 1})


@dataclass(frozen=True)
class TelegramServices:
    """The targeted sweep's collector and source (Phase 5, behind ORIGIN_ENABLE_TELEGRAM)."""

    collector: Collector
    source: PhotoSource


@dataclass(frozen=True)
class TraceServices:
    """What the discover, verify and date stages need, built once per worker."""

    providers: ProviderSetup
    runner: ProviderRunner
    fetcher: Fetcher
    thresholds: Thresholds
    max_pixels: int
    exiftool: str
    llm: LLMSetup = field(default_factory=lambda: LLMSetup(None, "not configured"))
    llm_runner: LLMRunner | None = None
    telegram: TelegramServices | None = None


def build_stages(
    *, blobs: BlobStore, embedder: SSCDEmbedder, trace: TraceServices | None = None
) -> list[Stage]:
    stages: list[Stage] = [IngestStage(blobs=blobs, embedder=embedder)]
    if trace is not None:
        verify = VerifyStage(
            fetcher=trace.fetcher,
            blobs=blobs,
            embedder=embedder,
            thresholds=trace.thresholds,
            max_pixels=trace.max_pixels,
        )
        date = DateStage(runner=trace.runner, blobs=blobs, exiftool=trace.exiftool)
        stages += [
            DiscoverStage(providers=trace.providers, runner=trace.runner, blobs=blobs),
            verify,
            date,
        ]
        index = next((a for a in trace.providers.adapters if isinstance(a, TelegramIndex)), None)
        if trace.telegram is not None and index is not None:
            stages.append(
                SweepStage(
                    collector=trace.telegram.collector,
                    source=trace.telegram.source,
                    index=index,
                    runner=trace.runner,
                    verify=verify,
                    date=date,
                )
            )
        stages += [
            BranchStage(
                blobs=blobs,
                thresholds=trace.thresholds,
                llm=trace.llm,
                llm_runner=trace.llm_runner,
            ),
        ]
    return stages
