"""The Telegram watchlist index: collect photos from listed public channels and fingerprint them.

Only channels on the watchlist (`telegram_channels`) are collected. Each photo is validated
like an upload, stored as an artefact with its fetch time and SHA-256, fingerprinted (pHash,
PDQ) and embedded with SSCD, so a trace can query the index like any other provider.
Collection is resumable: a channel remembers the newest message collected, and a photo
already in the index is skipped.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import structlog
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from origin_core.artefacts import store_artefact
from origin_core.db.models import TelegramChannel, TelegramPost
from origin_core.enums import ArtefactKind
from origin_core.ingest.hashes import fingerprint
from origin_core.ingest.validate import UploadRejected, decode_rgb, validate_upload
from origin_core.storage import BlobStore
from origin_core.telegram.preview import channel_name
from origin_worker.embedding import SSCDEmbedder
from origin_worker.telegram.sources import ChannelPhoto, PhotoSource, Throttled

log = structlog.get_logger(__name__)


class Embedder(Protocol):
    @property
    def model_id(self) -> str: ...

    async def embed(self, image: Image.Image) -> list[float]: ...


@dataclass(frozen=True)
class SSCDModel:
    """Adapts SSCDEmbedder (whose model id lives on its spec) to the Embedder protocol."""

    embedder: SSCDEmbedder

    @property
    def model_id(self) -> str:
        return self.embedder.spec.id

    async def embed(self, image: Image.Image) -> list[float]:
        return await self.embedder.embed(image)


@dataclass
class CollectReport:
    channel: str
    indexed: int = 0
    skipped: int = 0
    rejected: int = 0
    stopped: str | None = None


async def add_channel(
    sessions: async_sessionmaker[AsyncSession], text: str, *, added_by: str, note: str | None
) -> str:
    """Put a public channel on the watchlist. Returns its normalised username."""
    channel = channel_name(text)
    async with sessions.begin() as session:
        existing = (
            await session.execute(select(TelegramChannel).where(TelegramChannel.channel == channel))
        ).scalar_one_or_none()
        if existing is None:
            session.add(TelegramChannel(channel=channel, added_by=added_by, note=note))
    return channel


async def watchlist(sessions: async_sessionmaker[AsyncSession]) -> list[TelegramChannel]:
    async with sessions() as session:
        rows = await session.execute(select(TelegramChannel).order_by(TelegramChannel.channel))
        return list(rows.scalars())


@dataclass
class Collector:
    sessions: async_sessionmaker[AsyncSession]
    blobs: BlobStore
    embedder: Embedder
    max_pixels: int
    max_bytes: int = 20_000_000

    async def index_photo(self, photo: ChannelPhoto, *, via: str) -> TelegramPost | None:
        """Store one photo in the index. None if it is already there or not a usable image."""
        async with self.sessions() as session:
            exists = (
                await session.execute(
                    select(TelegramPost.id).where(
                        TelegramPost.channel == photo.channel,
                        TelegramPost.message_id == photo.message_id,
                        TelegramPost.photo_index == photo.photo_index,
                    )
                )
            ).first()
        if exists is not None:
            return None

        def prepare() -> tuple[Image.Image, str, str, str]:
            validate_upload(photo.data, max_bytes=self.max_bytes, max_pixels=self.max_pixels)
            image = decode_rgb(photo.data)
            prints = fingerprint(photo.data, image)
            return image, prints.sha256, prints.phash, prints.pdq

        image, sha256, phash, pdq = await asyncio.to_thread(prepare)
        embedding = await self.embedder.embed(image)
        forward = photo.forwarded_from
        async with self.sessions.begin() as session:
            artefact = await store_artefact(
                session,
                self.blobs,
                data=photo.data,
                kind=ArtefactKind.FETCHED_IMAGE,
                content_type=photo.content_type,
                source_url=photo.image_url,
                http_status=photo.http_status,
                http_headers=photo.http_headers,
                fetched_at=photo.fetched_at,
            )
            post = TelegramPost(
                channel=photo.channel,
                message_id=photo.message_id,
                photo_index=photo.photo_index,
                posted_at=photo.posted_at,
                text=photo.text,
                image_url=photo.image_url,
                image_artefact_id=artefact.id,
                forwarded_from_channel=forward.channel if forward else None,
                forwarded_from_message_id=forward.message_id if forward else None,
                forwarded_from_name=forward.name if forward else None,
                sha256=sha256,
                phash=phash,
                pdq=pdq,
                embedding=embedding,
                embedding_model=self.embedder.model_id,
                collected_via=via,
                collected_at=datetime.now(UTC),
            )
            session.add(post)
        return post

    async def collect(
        self,
        source: PhotoSource,
        channel: str,
        *,
        query: str | None = None,
        max_pages: int = 5,
        resume: bool = True,
    ) -> CollectReport:
        """Backfill one watchlist channel (or search it, with `query`) into the index."""
        report = CollectReport(channel)
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(TelegramChannel).where(TelegramChannel.channel == channel)
                )
            ).scalar_one_or_none()
        if row is None:
            report.stopped = "not on the watchlist"
            return report
        newer_than = row.newest_collected_id if resume and query is None else None
        newest = row.newest_collected_id or 0
        try:
            async for photo in source.photos(
                channel, newer_than=newer_than, query=query, max_pages=max_pages
            ):
                try:
                    post = await self.index_photo(photo, via=source.via)
                except UploadRejected as exc:
                    report.rejected += 1
                    log.info("telegram_photo_rejected", post=photo.message_id, error=exc.message)
                    continue
                if post is None:
                    report.skipped += 1
                else:
                    report.indexed += 1
                newest = max(newest, photo.message_id)
        except Throttled as exc:
            report.stopped = str(exc)
        if query is None:
            async with self.sessions.begin() as session:
                stored = await session.get_one(TelegramChannel, row.id)
                stored.newest_collected_id = newest or None
                stored.last_collected_at = datetime.now(UTC)
        log.info("telegram_collected", **report.__dict__)
        return report
