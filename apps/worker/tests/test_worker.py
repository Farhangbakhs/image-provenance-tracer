"""The worker job: settings, database, Redis, blob store, model and the ingest stage, together."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from testkit import SeedRun

from origin_core.db.models import Asset, Run
from origin_core.db.session import make_engine, make_sessionmaker
from origin_core.ingest.validate import decode_rgb
from origin_core.pipeline.events import EventType, RunEventBus
from origin_core.settings import get_settings
from origin_core.storage import FilesystemBlobStore
from origin_worker.embedding import SSCD_DISC_MIXUP, SSCDEmbedder, cosine
from origin_worker.main import execute_run, shutdown, startup

pytestmark = [pytest.mark.db, pytest.mark.redis]

PHOTO = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa" / "no-manifest.jpg"


async def test_execute_run_embeds_the_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_url: str,
    redis_url: str,
    models_dir: Path,
    embedder: SSCDEmbedder,
    seed_run: SeedRun,
) -> None:
    blob_dir = tmp_path / "blobs"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("BLOB_BACKEND", "filesystem")
    monkeypatch.setenv("BLOB_DIR", str(blob_dir))
    monkeypatch.setenv("ORIGIN_MODELS_DIR", str(models_dir))
    get_settings.cache_clear()

    image = PHOTO.read_bytes()
    run_id = await seed_run(image=image, blobs=FilesystemBlobStore(blob_dir))
    ctx: dict[str, Any] = {}
    await startup(ctx)
    try:
        assert await execute_run(ctx, str(run_id)) == "succeeded"
        events = await RunEventBus(ctx["redis"]).read(run_id, block_ms=None)
    finally:
        await shutdown(ctx)
        get_settings.cache_clear()

    engine = make_engine(database_url)
    async with make_sessionmaker(engine)() as session:
        asset = (
            await session.execute(
                select(Asset).join(Run, Run.asset_id == Asset.id).where(Run.id == run_id)
            )
        ).scalar_one()
        run = await session.get_one(Run, run_id)
    await engine.dispose()

    assert asset.embedding_model == SSCD_DISC_MIXUP.id
    assert asset.embedding is not None
    expected = embedder.embed_sync(decode_rgb(image))
    assert cosine([float(x) for x in asset.embedding], expected) == pytest.approx(1.0, abs=1e-4)
    assert run.stages["ingest"]["counts"] == {"embeddings_computed": 1}
    types = [event.type for _, event in events]
    assert EventType.STAGE_SUCCEEDED in types
    assert types[-1] is EventType.RUN_SUCCEEDED
