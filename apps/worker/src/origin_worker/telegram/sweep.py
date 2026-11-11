"""The targeted Telegram sweep: look on the watchlist around the earliest web date.

Runs after the web trace is dated (Phase 5, behind ORIGIN_ENABLE_TELEGRAM). It takes the
earliest date found on the web and a few keywords from the verified pages' titles, searches
every watchlist channel for them through the public preview, and indexes the photos posted
from `before_days` before that date to `after_days` after it. Then it asks the index about
the query image again; any post not already a candidate is verified and dated like every
other candidate.

Coverage is still the watchlist: a sweep that finds nothing says nothing about Telegram at
large.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from origin_core.db.models import Asset, Candidate, Run, Sighting
from origin_core.enums import CandidateStatus
from origin_core.pipeline.runner import StageContext, StageResult
from origin_core.providers.base import AssetRef
from origin_core.providers.runner import ProviderRunner
from origin_core.providers.telegram import TEXT_LIMIT, TelegramIndex
from origin_core.telegram.preview import post_url
from origin_worker.telegram.collector import Collector, watchlist
from origin_worker.telegram.sources import PhotoSource
from origin_worker.trace import DateStage, VerifyStage

_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
STOPWORDS = frozenset(
    [
        "about",
        "after",
        "again",
        "also",
        "amid",
        "back",
        "been",
        "being",
        "before",
        "from",
        "have",
        "here",
        "into",
        "just",
        "more",
        "most",
        "news",
        "over",
        "photo",
        "photos",
        "picture",
        "said",
        "says",
        "show",
        "shows",
        "some",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "today",
        "under",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "would",
        "your",
        "video",
        "watch",
    ]
)


def keywords(titles: list[str], limit: int) -> list[str]:
    """The most frequent content words across titles, first-seen order breaking ties."""
    counts: Counter[str] = Counter()
    first: dict[str, int] = {}
    for title in titles:
        for word in _WORD.findall(title.lower()):
            if word in STOPWORDS:
                continue
            counts[word] += 1
            first.setdefault(word, len(first))
    ranked = sorted(counts, key=lambda w: (-counts[w], first[w]))
    return ranked[:limit]


@dataclass
class SweepStage:
    collector: Collector
    source: PhotoSource
    index: TelegramIndex
    runner: ProviderRunner
    verify: VerifyStage
    date: DateStage
    before_days: int = 30
    after_days: int = 1
    max_keywords: int = 2
    #: How far back a chain of forwards is followed.
    max_forward_hops: int = 3
    name: str = "telegram_sweep"

    async def run(self, ctx: StageContext) -> StageResult:
        async with ctx.sessions.begin() as session:
            # A retried sweep starts again from its own additions.
            await session.execute(
                delete(Candidate).where(
                    Candidate.run_id == ctx.run_id, Candidate.raw["sweep"].astext == "true"
                )
            )
        counts: dict[str, int] = {}
        notes: dict[str, str] = {}
        await self._search(ctx, counts, notes)
        await self._follow_forwards(ctx, counts, notes)
        return StageResult(counts=counts, notes=notes)

    async def _add_and_check(self, ctx: StageContext, added: list[Candidate]) -> int:
        """Store new candidates, then verify and date them like any other. Returns verified."""
        if not added:
            return 0
        async with ctx.sessions.begin() as session:
            session.add_all(added)
        verified = await self.verify.verify_candidates(ctx, added, stage=self.name)
        await self.date.date_sightings(ctx, [c.id for c in added])
        return verified["verified"]

    async def _known_urls(self, ctx: StageContext) -> set[str | None]:
        async with ctx.sessions() as session:
            return set(
                (
                    await session.execute(
                        select(Candidate.page_url).where(Candidate.run_id == ctx.run_id)
                    )
                ).scalars()
            )

    async def _search(
        self, ctx: StageContext, counts: dict[str, int], notes: dict[str, str]
    ) -> None:
        async with ctx.sessions() as session:
            web = (
                await session.execute(
                    select(
                        Sighting.title,
                        func.coalesce(Sighting.date_upper, Sighting.date_lower).label("when"),
                    )
                    .join(Candidate, Candidate.id == Sighting.candidate_id)
                    .where(Sighting.run_id == ctx.run_id, Candidate.provider != self.index.name)
                )
            ).all()
            asset = (
                await session.execute(
                    select(Asset).join(Run, Run.asset_id == Asset.id).where(Run.id == ctx.run_id)
                )
            ).scalar_one()
        dates = [row.when for row in web if row.when is not None]
        if not dates:
            notes["sweep"] = "skipped: no dated web sighting to sweep around"
            return
        channels = [row.channel for row in await watchlist(ctx.sessions)]
        if not channels:
            notes["sweep"] = "skipped: the Telegram watchlist is empty"
            return
        earliest: datetime = min(dates)
        window = (
            earliest - timedelta(days=self.before_days),
            earliest + timedelta(days=self.after_days),
        )
        words = keywords([row.title for row in web if row.title], self.max_keywords)
        if not words:
            notes["sweep"] = "skipped: no keywords in the sightings' titles"
            return

        counts |= {"channels": len(channels), "indexed": 0}
        notes["sweep"] = (
            f"searched for {', '.join(words)} from {window[0]:%Y-%m-%d} to {window[1]:%Y-%m-%d}"
        )
        for channel in channels:
            for word in words:
                report = await self.collector.collect(
                    self.source, channel, query=word, max_pages=1, window=window
                )
                counts["indexed"] += report.indexed
                if report.stopped:
                    notes[channel] = f"stopped: {report.stopped}"
            await ctx.progress(self.name, **counts)

        subject = AssetRef(
            id=str(asset.id),
            sha256=asset.sha256,
            content_type=asset.content_type,
            data=b"",  # the index matches on the stored embedding and hash, not the bytes
            width=asset.width,
            height=asset.height,
        )
        outcome = await self.runner.run(self.index, subject, run_id=ctx.run_id)
        if not outcome.usable:
            notes["index"] = f"{outcome.status.value}: {outcome.error or 'no result'}"
            return
        known = await self._known_urls(ctx)
        added = [
            Candidate(
                run_id=ctx.run_id,
                provider_call_id=outcome.call_id,
                provider=self.index.name,
                page_url=hit.page_url,
                provider_date=hit.provider_date,
                provider_rank=hit.rank,
                raw={**hit.raw, "title": hit.title, "sweep": True},
            )
            for hit in outcome.hits
            if hit.page_url not in known
        ]
        counts["new_candidates"] = len(added)
        counts["verified"] = await self._add_and_check(ctx, added)

    async def _follow_forwards(
        self, ctx: StageContext, counts: dict[str, int], notes: dict[str, str]
    ) -> None:
        """Add the original of every verified Telegram post that names a public source post.

        The original's time comes from Telegram's own page for it. It is then verified like any
        candidate, so a forward header never makes anything a sighting on its own.
        """
        followed = 0
        confirmed = 0
        for _ in range(self.max_forward_hops):
            async with ctx.sessions() as session:
                forwarders = (
                    (
                        await session.execute(
                            select(Candidate).where(
                                Candidate.run_id == ctx.run_id,
                                Candidate.provider == self.index.name,
                                Candidate.status == CandidateStatus.VERIFIED,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            known = await self._known_urls(ctx)
            added: list[Candidate] = []
            for forwarder in forwarders:
                channel = forwarder.raw.get("forwarded_from_channel")
                number = forwarder.raw.get("forwarded_from_message_id")
                if not isinstance(channel, str) or not isinstance(number, int):
                    continue
                url = post_url(channel, number)
                if url in known:
                    continue
                known.add(url)
                post = await self.source.post(channel, number)
                if post is None or post.posted_at is None:
                    notes[url] = "forward source could not be read"
                    continue
                forward = post.forwarded_from
                added.append(
                    Candidate(
                        run_id=ctx.run_id,
                        provider_call_id=forwarder.provider_call_id,
                        provider=self.index.name,
                        page_url=url,
                        provider_date=post.posted_at,
                        raw={
                            "channel": channel,
                            "message_id": number,
                            "text": post.text[:TEXT_LIMIT],
                            "forwarded_from_channel": forward.channel if forward else None,
                            "forwarded_from_message_id": forward.message_id if forward else None,
                            "forwarded_from_name": forward.name if forward else None,
                            "collected_via": self.source.via,
                            "found_by": "forward",
                            "forward_of": forwarder.page_url,
                            "title": f"Telegram: {channel}/{number}",
                            "sweep": True,
                        },
                    )
                )
            if not added:
                break
            followed += len(added)
            confirmed += await self._add_and_check(ctx, added)
        if followed:
            counts["forward_sources"] = followed
            counts["forward_sources_verified"] = confirmed
