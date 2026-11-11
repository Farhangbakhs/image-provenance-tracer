"""The Telegram index as a provider: nearest posts by embedding or pHash, never replayed.

SYNTHETIC: posts are written straight into the index with hand-made vectors and hashes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import SeedRun

from origin_core.db.models import Artefact, Asset, Run, TelegramPost
from origin_core.db.session import make_sessionmaker
from origin_core.enums import ArtefactKind, ProviderCallStatus
from origin_core.providers.base import AssetRef
from origin_core.providers.fixtures import FixtureStore
from origin_core.providers.runner import ProviderRunner, RetryPolicy
from origin_core.providers.telegram import TelegramIndex
from origin_core.settings import ProviderMode
from origin_core.storage import FilesystemBlobStore

pytestmark = pytest.mark.db

MODEL = "test-model@0000000"


def _vector(*head: float) -> list[float]:
    return [*head, *([0.0] * (512 - len(head)))]


async def _setup(db_engine: AsyncEngine, seed_run: SeedRun) -> tuple[uuid.UUID, AssetRef, str]:
    run_id = await seed_run()
    sessions = make_sessionmaker(db_engine)
    tag = uuid.uuid4().hex[:8]
    async with sessions.begin() as session:
        run = await session.get_one(Run, run_id)
        await session.execute(
            update(Asset)
            .where(Asset.id == run.asset_id)
            .values(embedding=_vector(1.0), embedding_model=MODEL, phash="ffff0000ffff0000")
        )
        asset = await session.get_one(Asset, run.asset_id)
        artefact = Artefact(
            kind=ArtefactKind.FETCHED_IMAGE,
            sha256="ab" * 32,
            storage_key=f"sha256/ab/{tag}",
            content_type="image/jpeg",
            byte_size=1,
        )
        session.add(artefact)
        await session.flush()
        rows = [
            # Same picture by embedding; posted earliest; a forward of another channel's post.
            (f"near_{tag}", 3, _vector(0.95, 0.31), "0000000000000000", ("first_hand", 7)),
            # Unrelated by embedding, but the same pHash: reported through the hash route.
            (f"hash_{tag}", 4, _vector(0.0, 1.0), "ffff0000ffff0001", None),
            # Unrelated by both.
            (f"far_{tag}", 5, _vector(0.0, 0.0, 1.0), "0000000000000000", None),
        ]
        for channel, message_id, vector, phash, forward in rows:
            session.add(
                TelegramPost(
                    channel=channel,
                    message_id=message_id,
                    posted_at=datetime(2024, 10, 29, 18, message_id, tzinfo=UTC),
                    text=f"post {message_id}",
                    image_url=f"https://cdn.telesco.pe/{channel}.jpg",
                    image_artefact_id=artefact.id,
                    forwarded_from_channel=forward[0] if forward else None,
                    forwarded_from_message_id=forward[1] if forward else None,
                    sha256="cd" * 32,
                    phash=phash,
                    pdq="0" * 64,
                    embedding=vector,
                    embedding_model=MODEL,
                    collected_via="preview",
                    collected_at=datetime(2026, 11, 11, tzinfo=UTC),
                )
            )
        ref = AssetRef(
            id=str(asset.id),
            sha256=asset.sha256,
            content_type="image/jpeg",
            data=b"",
            width=1,
            height=1,
        )
    return run_id, ref, tag


async def test_index_reports_neighbours_by_embedding_or_phash(
    db_engine: AsyncEngine, seed_run: SeedRun
) -> None:
    _, ref, tag = await _setup(db_engine, seed_run)
    adapter = TelegramIndex(make_sessionmaker(db_engine))
    async with httpx.AsyncClient() as client:
        raw = await adapter.fetch(ref, client)
    # The test database is shared; look only at this test's posts.
    hits = [h for h in adapter.parse(raw.body) if str(h.raw["channel"]).endswith(tag)]
    channels = [str(h.raw["channel"]) for h in hits]
    assert [c.split("_")[0] for c in channels] == ["near", "hash"]
    near = hits[0]
    assert near.page_url == f"https://t.me/{channels[0]}/3"
    assert near.image_url is None
    assert near.provider_date == datetime(2024, 10, 29, 18, 3, tzinfo=UTC)
    assert near.raw["forwarded_from_channel"] == "first_hand"
    assert near.raw["cosine"] == pytest.approx(0.95, abs=1e-3)
    assert hits[1].raw["phash_distance"] == 1


async def test_replay_mode_still_queries_the_local_index(
    db_engine: AsyncEngine, seed_run: SeedRun, tmp_path: Path
) -> None:
    run_id, ref, tag = await _setup(db_engine, seed_run)
    sessions = make_sessionmaker(db_engine)
    runner = ProviderRunner(
        sessions=sessions,
        blobs=FilesystemBlobStore(tmp_path),
        http=httpx.AsyncClient(),
        policies={},
        retry=RetryPolicy(attempts=1),
        mode=ProviderMode.REPLAY,
        fixtures=FixtureStore((tmp_path / "recordings",)),
    )
    first = await runner.run(TelegramIndex(sessions), ref, run_id=run_id)
    second = await runner.run(TelegramIndex(sessions), ref, run_id=run_id)
    assert first.status is ProviderCallStatus.OK and second.status is ProviderCallStatus.OK
    assert len([h for h in first.hits if str(h.raw["channel"]).endswith(tag)]) == 2
    assert not (tmp_path / "recordings").exists()
