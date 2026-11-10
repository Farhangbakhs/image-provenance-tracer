"""Fixtures shared by every Python test suite. Service-backed tests use real services.

* Postgres with pgvector: TEST_DATABASE_URL (default: the compose server, database
  `origin_test`, dropped, recreated and migrated to head once per session, so the tests also
  exercise the migrations).
* Redis: TEST_REDIS_URL (default: the compose Redis, database 15, flushed per session).

Without a reachable service its tests are skipped locally. CI sets ORIGIN_REQUIRE_SERVICES=1
so a missing service fails the run instead of silently hiding tests.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from alembic import command
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from origin_core.db.migrate import alembic_config
from origin_core.db.models import Artefact, Asset, Case, Run
from origin_core.db.session import make_engine, make_sessionmaker
from origin_core.enums import ArtefactKind, C2PAState

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://origin:origin@127.0.0.1:5432/origin_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")


def _unavailable(service: str, exc: BaseException) -> None:
    if os.environ.get("ORIGIN_REQUIRE_SERVICES") == "1":
        raise exc
    pytest.skip(f"{service} not reachable ({exc}); run `make dev` first")


async def _recreate_database(url: str) -> None:
    parsed = make_url(url)
    name = parsed.database
    assert name and name.endswith("_test"), "refusing to recreate a database not named *_test"
    admin = create_async_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
async def db_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    try:
        await _recreate_database(database_url)
    except (OSError, OperationalError) as exc:
        _unavailable("Postgres", exc)
    await asyncio.to_thread(command.upgrade, alembic_config(database_url), "head")
    engine = make_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back after the test."""
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = make_sessionmaker(db_engine)(
            bind=connection, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture(scope="session")
async def redis_url() -> AsyncIterator[str]:
    client = Redis.from_url(TEST_REDIS_URL)
    try:
        await client.flushdb()  # pyright: ignore[reportUnknownMemberType]
    except (OSError, RedisConnectionError) as exc:
        await client.aclose()
        _unavailable("Redis", exc)
    await client.aclose()
    yield TEST_REDIS_URL


@pytest.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url)
    yield client
    await client.aclose()


SeedRun = Callable[[], Awaitable[uuid.UUID]]


@pytest.fixture
def seed_run(db_engine: AsyncEngine) -> SeedRun:
    """Insert (and commit) a case, an asset and a queued run; return the run id."""

    async def seed() -> uuid.UUID:
        sha = uuid.uuid4().hex * 2
        async with make_sessionmaker(db_engine).begin() as session:
            case = Case(title="seeded")
            original = Artefact(
                kind=ArtefactKind.ORIGINAL,
                sha256=sha,
                storage_key=f"sha256/{sha[:2]}/{sha}",
                content_type="image/png",
                byte_size=1,
            )
            session.add_all([case, original])
            await session.flush()
            asset = Asset(
                case_id=case.id,
                original_artefact_id=original.id,
                content_type="image/png",
                width=1,
                height=1,
                sha256=sha,
                phash="0" * 16,
                dhash="0" * 16,
                pdq="0" * 64,
                pdq_quality=0,
                c2pa_state=C2PAState.NONE,
            )
            session.add(asset)
            await session.flush()
            run = Run(case_id=case.id, asset_id=asset.id)
            session.add(run)
            await session.flush()
            return run.id

    return seed
