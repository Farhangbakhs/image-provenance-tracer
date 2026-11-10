"""The ingest stage embeds once, and reuses an embedding made by the same model."""

from __future__ import annotations

from pathlib import Path

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import SeedRun

from origin_core.db.session import make_sessionmaker
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.runner import StageContext
from origin_core.storage import FilesystemBlobStore
from origin_worker.embedding import SSCDEmbedder
from origin_worker.stages import IngestStage

pytestmark = [pytest.mark.db, pytest.mark.redis]

PHOTO = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa" / "no-manifest.jpg"


async def test_ingest_embeds_once(
    db_engine: AsyncEngine,
    redis: Redis,
    tmp_path: Path,
    embedder: SSCDEmbedder,
    seed_run: SeedRun,
) -> None:
    blobs = FilesystemBlobStore(tmp_path)
    run_id = await seed_run(image=PHOTO.read_bytes(), blobs=blobs)
    stage = IngestStage(blobs=blobs, embedder=embedder)
    ctx = StageContext(
        run_id=run_id, sessions=make_sessionmaker(db_engine), events=RunEventBus(redis)
    )

    first = await stage.run(ctx)
    second = await stage.run(ctx)

    assert first.counts == {"embeddings_computed": 1}
    assert second.counts == {"embeddings_reused": 1}
