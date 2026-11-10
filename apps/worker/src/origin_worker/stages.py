"""Pipeline stages executed by the worker, in the order of origin_core.pipeline.registry.

Ingest is split across two processes on purpose. The API validates, stores, fingerprints and
reads metadata and Content Credentials at upload time, because those are fast and an upload
should be refused at the door. The SSCD embedding needs PyTorch and a 99 MB model, so it runs
here, as the pipeline's ingest stage, and the API never loads the model.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from origin_core.db.models import Artefact, Asset, Run
from origin_core.ingest.validate import decode_rgb
from origin_core.pipeline.runner import Stage, StageContext, StageResult
from origin_core.storage import BlobStore
from origin_worker.embedding import SSCDEmbedder


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


def build_stages(*, blobs: BlobStore, embedder: SSCDEmbedder) -> list[Stage]:
    return [IngestStage(blobs=blobs, embedder=embedder)]
