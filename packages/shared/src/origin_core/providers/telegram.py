"""The Telegram watchlist index as a provider (Phase 5, behind ORIGIN_ENABLE_TELEGRAM).

There is no reverse image search on Telegram, so this adapter asks ORIGIN's own index of
watchlist photos (`telegram_posts`) for the query image's nearest neighbours by SSCD
embedding, plus any photo within the near-duplicate pHash distance. A hit is a candidate like
any other: its page is the post's own page (`t.me/<channel>/<id>`), which the verifier fetches
and checks before anything becomes a sighting.

The adapter is `local`: it reads ORIGIN's database, not a remote service, so the runner never
caches, meters or replays it; a cached answer would hide posts indexed since.

Coverage is the watchlist. No hit means "not in the channels ORIGIN indexes", nothing more.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from origin_core.db.models import Asset, TelegramPost
from origin_core.providers.base import AssetRef, CandidateHit, ProviderError, RawResponse
from origin_core.telegram.preview import post_url

#: Nearest neighbours considered, and the SSCD cosine below which they are not reported. Both
#: are generous: the verifier, not the index, decides what matches.
NEIGHBOURS = 50
MIN_COSINE = 0.5
#: pHash distance that is reported whatever the embedding says (the v2 near-duplicate cut).
MAX_PHASH = 8
TEXT_LIMIT = 500


def _hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


class TelegramIndex:
    name: str = "telegram"
    quota_key: str = "telegram"
    unit_cost: int = 0
    requires_public_url: bool = False
    local: bool = True
    recipients: tuple[str, ...] = ("nobody: the Telegram index is ORIGIN's own database",)

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    def params(self) -> dict[str, Any]:
        return {"neighbours": NEIGHBOURS, "min_cosine": MIN_COSINE, "max_phash": MAX_PHASH}

    async def fetch(self, subject: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        async with self._sessions() as session:
            asset = await session.get(Asset, uuid.UUID(subject.id))
            if asset is None or asset.embedding is None or asset.embedding_model is None:
                raise ProviderError("the query image has no embedding yet", retryable=False)
            distance = TelegramPost.embedding.cosine_distance(asset.embedding)
            near = (
                await session.execute(
                    select(TelegramPost, (1 - distance).label("cosine"))
                    .where(TelegramPost.embedding_model == asset.embedding_model)
                    .order_by(distance)
                    .limit(NEIGHBOURS)
                )
            ).all()
            same_phash = (
                await session.execute(
                    select(TelegramPost).where(TelegramPost.phash == asset.phash).limit(NEIGHBOURS)
                )
            ).scalars()
            found: dict[uuid.UUID, tuple[TelegramPost, float | None]] = {
                post.id: (post, float(cosine)) for post, cosine in near
            }
            for post in same_phash:
                found.setdefault(post.id, (post, None))
            matches: list[dict[str, Any]] = []
            for post, cosine in found.values():
                phash_distance = _hamming(asset.phash, post.phash)
                if (cosine is None or cosine < MIN_COSINE) and phash_distance > MAX_PHASH:
                    continue
                matches.append(
                    {
                        "channel": post.channel,
                        "message_id": post.message_id,
                        "photo_index": post.photo_index,
                        "post_url": post_url(post.channel, post.message_id),
                        "posted_at": post.posted_at.isoformat(),
                        "text": post.text[:TEXT_LIMIT],
                        "cosine": None if cosine is None else round(cosine, 4),
                        "phash_distance": phash_distance,
                        "forwarded_from_channel": post.forwarded_from_channel,
                        "forwarded_from_message_id": post.forwarded_from_message_id,
                        "forwarded_from_name": post.forwarded_from_name,
                        "collected_via": post.collected_via,
                    }
                )
        matches.sort(key=lambda m: (-(m["cosine"] or 0.0), m["phash_distance"]))
        return RawResponse(json.dumps({"matches": matches}).encode(), units=0)

    def parse(self, body: bytes) -> list[CandidateHit]:
        payload = cast(dict[str, Any], json.loads(body))
        hits: list[CandidateHit] = []
        for rank, item in enumerate(cast(list[dict[str, Any]], payload.get("matches") or []), 1):
            hits.append(
                CandidateHit(
                    page_url=str(item["post_url"]),
                    image_url=None,  # the verifier reads the post's page for its current photo
                    provider_date=datetime.fromisoformat(str(item["posted_at"])),
                    rank=rank,
                    title=f"Telegram: {item['channel']}/{item['message_id']}",
                    raw={k: v for k, v in item.items() if k != "post_url"},
                )
            )
        return hits
