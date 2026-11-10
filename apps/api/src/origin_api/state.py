"""Process-wide resources, created in the app lifespan and reached through dependencies."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from origin_core.db.session import make_engine, make_sessionmaker
from origin_core.pipeline.events import RunEventBus
from origin_core.settings import Settings
from origin_core.storage import BlobStore, make_blob_store


@dataclass
class AppState:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis
    blobs: BlobStore
    events: RunEventBus


def lifespan_for(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = make_engine(settings.database_url)
        redis = Redis.from_url(settings.redis_url)
        app.state.origin = AppState(
            settings=settings,
            engine=engine,
            sessions=make_sessionmaker(engine),
            redis=redis,
            blobs=make_blob_store(settings),
            events=RunEventBus(redis),
        )
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()

    return lifespan


def get_state(request: Request) -> AppState:
    return cast(AppState, request.app.state.origin)


State = Annotated[AppState, Depends(get_state)]


async def get_session(state: State) -> AsyncIterator[AsyncSession]:
    async with state.sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
