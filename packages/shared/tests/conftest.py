"""Shared fixtures. Database tests run against a real Postgres with pgvector.

Set TEST_DATABASE_URL (default: the compose database server, database `origin_test`).
The database is dropped and recreated once per session and migrated to head, so the
tests also exercise the migrations themselves.

Without a reachable database the DB tests are skipped locally; CI sets
ORIGIN_REQUIRE_DB=1 so that a missing database fails the run instead of hiding tests.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from origin_core.db.migrate import alembic_config
from origin_core.db.session import make_engine, make_sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://origin:origin@localhost:5432/origin_test"
)


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
async def db_engine() -> AsyncIterator[AsyncEngine]:
    try:
        await _recreate_database(TEST_DATABASE_URL)
    except (OSError, OperationalError) as exc:
        if os.environ.get("ORIGIN_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres not reachable for DB tests ({exc}); run `make dev` first")
    await asyncio.to_thread(command.upgrade, alembic_config(TEST_DATABASE_URL), "head")
    engine = make_engine(TEST_DATABASE_URL)
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
