"""Discover, verify and date: from provider hits to dated, verified sightings.

discover  asks every enabled provider about the query image and stores each hit as a
          candidate. A candidate is never evidence.
verify    fetches each candidate's image (or the images on its page) through the hardened
          fetcher and classifies it against the query. Only a match becomes a sighting, with
          the fetched image and page stored as artefacts.
date      gathers every timestamp signal for each sighting into timestamp_evidence and applies
          the dating rule.

Each stage reads only the database and object store, and is safe to re-run: a retried stage
clears what an earlier attempt of the same stage wrote, then starts again.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import structlog
from sqlalchemy import delete, select, update

from origin_core.artefacts import store_artefact
from origin_core.dating.rule import DEFAULT_READING, Signal, date_sighting
from origin_core.db.models import Artefact, Asset, Candidate, Run, Sighting, TimestampEvidence
from origin_core.enums import (
    ArtefactKind,
    BoundType,
    C2PAState,
    CandidateStatus,
    Confidence,
    EvidenceKind,
    MatchClass,
)
from origin_core.fetch import (
    IMAGE_POLICY,
    PAGE_POLICY,
    FetchBlocked,
    Fetcher,
    FetchFailed,
    FetchResult,
)
from origin_core.ingest.c2pa import read_c2pa
from origin_core.ingest.hashes import fingerprint
from origin_core.ingest.metadata import MetadataUnavailable, read_metadata
from origin_core.ingest.validate import UploadRejected, decode_rgb, validate_upload
from origin_core.pages import Page, parse_page
from origin_core.pipeline.runner import StageContext, StageResult
from origin_core.providers.base import AssetRef, UrlSubject
from origin_core.providers.registry import ProviderSetup
from origin_core.providers.runner import ProviderRunner
from origin_core.providers.telegram import TelegramIndex
from origin_core.providers.wayback import WaybackFirstCapture, first_capture
from origin_core.storage import BlobStore
from origin_worker.embedding import SSCDEmbedder
from origin_worker.matching.classify import MatchResult, Side, classify
from origin_worker.matching.thresholds import Thresholds

log = structlog.get_logger(__name__)

#: Better match classes first.
_RANK = {MatchClass.EXACT: 0, MatchClass.NEAR_DUPLICATE: 1, MatchClass.DERIVATIVE: 2}


async def _asset_bytes(ctx: StageContext, blobs: BlobStore) -> tuple[Asset, bytes]:
    async with ctx.sessions() as session:
        asset, key = (
            await session.execute(
                select(Asset, Artefact.storage_key)
                .join(Run, Run.asset_id == Asset.id)
                .join(Artefact, Artefact.id == Asset.original_artefact_id)
                .where(Run.id == ctx.run_id)
            )
        ).one()
    return asset, await blobs.get(key)


# --- discover --------------------------------------------------------------------------------


@dataclass
class DiscoverStage:
    providers: ProviderSetup
    runner: ProviderRunner
    blobs: BlobStore
    name: str = "discover"

    async def run(self, ctx: StageContext) -> StageResult:
        asset, data = await _asset_bytes(ctx, self.blobs)
        subject = AssetRef(
            id=str(asset.id),
            sha256=asset.sha256,
            content_type=asset.content_type,
            data=data,
            width=asset.width,
            height=asset.height,
        )
        async with ctx.sessions.begin() as session:
            await session.execute(delete(Candidate).where(Candidate.run_id == ctx.run_id))
            await session.execute(
                update(Run)
                .where(Run.id == ctx.run_id)
                .values(providers=[a.name for a in self.providers.adapters])
            )

        counts: dict[str, int] = {}
        quota: dict[str, int] = {}
        notes = {name: f"not queried: {why}" for name, why in self.providers.unavailable.items()}
        for adapter in self.providers.adapters:
            outcome = await self.runner.run(adapter, subject, run_id=ctx.run_id)
            quota[adapter.name] = outcome.units
            if not outcome.usable:
                notes[adapter.name] = f"{outcome.status.value}: {outcome.error or 'no result'}"
                counts[f"{adapter.name}_hits"] = 0
                continue
            async with ctx.sessions.begin() as session:
                for hit in outcome.hits:
                    if not (hit.page_url or hit.image_url):
                        continue
                    session.add(
                        Candidate(
                            run_id=ctx.run_id,
                            provider_call_id=outcome.call_id,
                            provider=adapter.name,
                            page_url=hit.page_url,
                            image_url=hit.image_url,
                            provider_date=hit.provider_date,
                            provider_rank=hit.rank,
                            raw={**hit.raw, "title": hit.title},
                        )
                    )
            counts[f"{adapter.name}_hits"] = len(outcome.hits)
            await ctx.progress(self.name, **counts)
        if not self.providers.adapters:
            notes["providers"] = "no provider is enabled, so nothing was searched"
        return StageResult(counts=counts, quota=quota, notes=notes)


# --- verify ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Image:
    url: str
    fetch: FetchResult
    side: Side


@dataclass
class _Cache:
    pages: dict[str, tuple[FetchResult, Page] | str] = field(default_factory=dict[str, Any])
    images: dict[str, _Image | str] = field(default_factory=dict[str, Any])
    locks: dict[str, asyncio.Lock] = field(default_factory=dict[str, asyncio.Lock])

    def lock(self, key: str) -> asyncio.Lock:
        return self.locks.setdefault(key, asyncio.Lock())


@dataclass
class VerifyStage:
    fetcher: Fetcher
    blobs: BlobStore
    embedder: SSCDEmbedder
    thresholds: Thresholds
    max_pixels: int
    concurrency: int = 3
    name: str = "verify"

    async def _page(self, cache: _Cache, url: str) -> tuple[FetchResult, Page] | str:
        async with cache.lock(f"page:{url}"):
            if url not in cache.pages:
                try:
                    result = await self.fetcher.get(url, PAGE_POLICY)
                    if result.status != 200:
                        cache.pages[url] = f"page HTTP {result.status}"
                    else:
                        cache.pages[url] = (result, parse_page(result.final_url, result.body))
                except (FetchBlocked, FetchFailed) as exc:
                    cache.pages[url] = f"page fetch failed: {exc}"
            return cache.pages[url]

    async def _image(self, cache: _Cache, url: str) -> _Image | str:
        async with cache.lock(f"image:{url}"):
            if url not in cache.images:
                cache.images[url] = await self._load_image(url)
            return cache.images[url]

    async def _load_image(self, url: str) -> _Image | str:
        try:
            result = await self.fetcher.get(url, IMAGE_POLICY)
        except (FetchBlocked, FetchFailed) as exc:
            return f"image fetch failed: {exc}"
        if result.status != 200:
            return f"image HTTP {result.status}"
        data = result.body

        def prepare() -> tuple[Side, None] | tuple[None, str]:
            try:
                validate_upload(data, max_bytes=IMAGE_POLICY.max_bytes, max_pixels=self.max_pixels)
            except UploadRejected as exc:
                return None, f"not a usable image: {exc.message}"
            image = decode_rgb(data)
            return Side(fingerprint(data, image), [], image), None

        side, error = await asyncio.to_thread(prepare)
        if side is None:
            return error or "not a usable image"
        embedding = await self.embedder.embed(side.image)
        return _Image(url, result, Side(side.fingerprints, embedding, side.image))

    async def _query(self, ctx: StageContext) -> Side:
        asset, data = await _asset_bytes(ctx, self.blobs)
        if asset.embedding is None:
            raise RuntimeError("the query image has no embedding; the ingest stage must run first")
        query_image = await asyncio.to_thread(decode_rgb, data)
        return Side(
            await asyncio.to_thread(fingerprint, data, query_image),
            [float(x) for x in asset.embedding],
            query_image,
        )

    async def run(self, ctx: StageContext) -> StageResult:
        async with ctx.sessions.begin() as session:
            await session.execute(delete(Sighting).where(Sighting.run_id == ctx.run_id))
            await session.execute(
                update(Candidate)
                .where(Candidate.run_id == ctx.run_id)
                .values(status=CandidateStatus.PENDING, reject_reason=None)
            )
            candidates = (
                (await session.execute(select(Candidate).where(Candidate.run_id == ctx.run_id)))
                .scalars()
                .all()
            )

        counts = await self.verify_candidates(ctx, list(candidates))
        return StageResult(counts={"candidates": len(candidates), **counts})

    async def verify_candidates(
        self, ctx: StageContext, candidates: list[Candidate], *, stage: str | None = None
    ) -> dict[str, int]:
        """Verify these pending candidates (the whole run, or a later stage's additions)."""
        counts: dict[str, int] = {"verified": 0, "unrelated": 0, "fetch_failed": 0}
        if not candidates:
            return counts
        query = await self._query(ctx)
        cache = _Cache()
        gate = asyncio.Semaphore(self.concurrency)
        done = 0

        async def verify_one(candidate: Candidate) -> None:
            nonlocal done
            async with gate:
                status, _ = await self._verify(ctx, query, cache, candidate)
            counts[status.value] = counts.get(status.value, 0) + 1
            done += 1
            if done % 5 == 0:
                await ctx.progress(stage or self.name, checked=done, verified=counts["verified"])

        await asyncio.gather(*(verify_one(c) for c in candidates))
        return counts

    async def _verify(
        self, ctx: StageContext, query: Side, cache: _Cache, candidate: Candidate
    ) -> tuple[CandidateStatus, str | None]:
        page: tuple[FetchResult, Page] | None = None
        page_error: str | None = None
        if candidate.page_url:
            loaded = await self._page(cache, candidate.page_url)
            if isinstance(loaded, str):
                page_error = loaded
            else:
                page = loaded

        if candidate.image_url:
            urls = [candidate.image_url]
        elif page is not None:
            urls = page[1].images
        else:
            return await self._reject(
                ctx, candidate, CandidateStatus.FETCH_FAILED, page_error or "no URL"
            )

        best: tuple[_Image, MatchResult] | None = None
        last_reason = "no image on the page"
        for url in urls:
            loaded_image = await self._image(cache, url)
            if isinstance(loaded_image, str):
                last_reason = loaded_image
                continue
            result = classify(query, loaded_image.side, self.thresholds)
            if not result.related:
                last_reason = result.reason
                continue
            assert result.match_class is not None
            if (
                best is None
                or _RANK[result.match_class] < _RANK[best[1].match_class or MatchClass.DERIVATIVE]
            ):
                best = (loaded_image, result)
            if result.match_class in (MatchClass.EXACT, MatchClass.NEAR_DUPLICATE):
                break

        if best is None:
            status = (
                CandidateStatus.FETCH_FAILED
                if last_reason.startswith(("image fetch", "image HTTP", "page"))
                else CandidateStatus.UNRELATED
            )
            return await self._reject(ctx, candidate, status, last_reason)

        image, match = best
        async with ctx.sessions.begin() as session:
            image_artefact = await store_artefact(
                session,
                self.blobs,
                data=image.fetch.body,
                kind=ArtefactKind.FETCHED_IMAGE,
                content_type=image.fetch.content_type or "application/octet-stream",
                source_url=image.fetch.final_url,
                http_status=image.fetch.status,
                http_headers=image.fetch.headers,
                fetched_at=image.fetch.fetched_at,
            )
            page_artefact_id: uuid.UUID | None = None
            if page is not None:
                page_artefact = await store_artefact(
                    session,
                    self.blobs,
                    data=page[0].body,
                    kind=ArtefactKind.PAGE_HTML,
                    content_type=page[0].content_type or "text/html",
                    source_url=page[0].final_url,
                    http_status=page[0].status,
                    http_headers=page[0].headers,
                    fetched_at=page[0].fetched_at,
                )
                page_artefact_id = page_artefact.id
            session.add(
                Sighting(
                    run_id=ctx.run_id,
                    candidate_id=candidate.id,
                    image_artefact_id=image_artefact.id,
                    page_artefact_id=page_artefact_id,
                    page_url=candidate.page_url,
                    image_url=image.url,
                    title=(page[1].title if page else None) or candidate.raw.get("title"),
                    match_class=match.match_class,
                    phash_distance=match.phash_distance,
                    pdq_distance=match.pdq_distance,
                    sscd_cosine=match.sscd_cosine,
                    homography_inliers=match.geometry.inliers if match.geometry else None,
                    transform=match.transform(),
                    threshold_version=match.thresholds_version,
                    embedding=image.side.embedding,
                )
            )
            await session.execute(
                update(Candidate)
                .where(Candidate.id == candidate.id)
                .values(status=CandidateStatus.VERIFIED, reject_reason=match.reason)
            )
        return CandidateStatus.VERIFIED, match.reason

    @staticmethod
    async def _reject(
        ctx: StageContext, candidate: Candidate, status: CandidateStatus, reason: str
    ) -> tuple[CandidateStatus, str | None]:
        async with ctx.sessions.begin() as session:
            await session.execute(
                update(Candidate)
                .where(Candidate.id == candidate.id)
                .values(status=status, reject_reason=reason)
            )
        return status, reason


# --- date ------------------------------------------------------------------------------------


@dataclass
class DateStage:
    runner: ProviderRunner
    blobs: BlobStore
    exiftool: str
    name: str = "date"

    async def _wayback(self, ctx: StageContext, url: str | None) -> tuple[datetime, str] | None:
        if not url:
            return None
        outcome = await self.runner.run(WaybackFirstCapture(), UrlSubject(url), run_id=ctx.run_id)
        capture = first_capture(outcome.hits) if outcome.usable else None
        return (capture.captured_at, capture.archive_url) if capture else None

    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult(counts=await self.date_sightings(ctx))

    async def date_sightings(
        self, ctx: StageContext, candidate_ids: list[uuid.UUID] | None = None
    ) -> dict[str, int]:
        """Date the run's sightings, or only those verified from `candidate_ids`."""
        query = (
            select(Sighting, Candidate)
            .join(Candidate, Candidate.id == Sighting.candidate_id)
            .where(Sighting.run_id == ctx.run_id)
        )
        if candidate_ids is not None:
            query = query.where(Candidate.id.in_(candidate_ids))
        async with ctx.sessions() as session:
            rows = (await session.execute(query)).all()
        counts: dict[str, int] = {"sightings": len(rows), "signals": 0}
        for sighting, candidate in rows:
            signals = await self._signals(ctx, sighting, candidate)
            counts["signals"] += len(signals)
            await self._store(ctx, sighting.id, signals)
        return counts

    async def _signals(
        self, ctx: StageContext, sighting: Sighting, candidate: Candidate
    ) -> list[tuple[EvidenceKind, datetime, BoundType, Confidence, str | None, dict[str, Any]]]:
        found: list[
            tuple[EvidenceKind, datetime, BoundType, Confidence, str | None, dict[str, Any]]
        ] = []

        def add(
            kind: EvidenceKind,
            value: datetime,
            url: str | None,
            detail: dict[str, Any],
            *,
            bound: BoundType | None = None,
            confidence: Confidence | None = None,
        ) -> None:
            default_bound, default_confidence = DEFAULT_READING[kind]
            found.append(
                (kind, value, bound or default_bound, confidence or default_confidence, url, detail)
            )

        async with ctx.sessions() as session:
            image = await session.get_one(Artefact, sighting.image_artefact_id)
            page = (
                await session.get(Artefact, sighting.page_artefact_id)
                if sighting.page_artefact_id
                else None
            )

        observed = page or image
        add(
            EvidenceKind.OBSERVED,
            observed.fetched_at,
            observed.source_url,
            {"artefact": str(observed.id)},
        )

        for kind, url in (
            (EvidenceKind.WAYBACK_PAGE, sighting.page_url),
            (EvidenceKind.WAYBACK_IMAGE, sighting.image_url),
        ):
            capture = await self._wayback(ctx, url)
            if capture:
                add(kind, capture[0], url, {"archive_url": capture[1]})

        if candidate.provider_date is not None and candidate.provider == TelegramIndex.name:
            # The message time Telegram itself showed when ORIGIN collected the post.
            add(
                EvidenceKind.PLATFORM,
                candidate.provider_date,
                candidate.page_url,
                {
                    "platform": "telegram",
                    "channel": candidate.raw.get("channel"),
                    "message_id": candidate.raw.get("message_id"),
                    "collected_via": candidate.raw.get("collected_via"),
                },
            )
        elif candidate.provider_date is not None:
            # Lens shows the date a result was posted: Google's reading of the page, a claim.
            add(
                EvidenceKind.PROVIDER_CRAWL,
                candidate.provider_date,
                candidate.page_url,
                {"provider": candidate.provider, "shown_as": candidate.raw.get("date")},
                bound=BoundType.CLAIMED,
                confidence=Confidence.MEDIUM,
            )

        if page is not None:
            parsed = parse_page(page.source_url or "", await self.blobs.get(page.storage_key))
            if parsed.published:
                add(
                    EvidenceKind.PAGE_METADATA,
                    parsed.published.value,
                    page.source_url,
                    {"source": parsed.published.source, "day_only": parsed.published.day_only},
                    confidence=Confidence.LOW
                    if parsed.published.source == "htmldate"
                    else Confidence.MEDIUM,
                )

        last_modified = (image.http_headers or {}).get("last-modified")
        if isinstance(last_modified, str):
            with contextlib.suppress(TypeError, ValueError):
                add(
                    EvidenceKind.HTTP_LAST_MODIFIED,
                    parsedate_to_datetime(last_modified),
                    image.source_url,
                    {"header": last_modified},
                )

        image_bytes = await self.blobs.get(image.storage_key)
        try:
            metadata = await read_metadata(image_bytes, exiftool=self.exiftool)
            capture_time = metadata.summary.capture_time
            if capture_time and capture_time.utc:
                add(
                    EvidenceKind.EXIF,
                    capture_time.utc,
                    image.source_url,
                    {"tag": capture_time.tag, "stated": capture_time.stated},
                )
        except MetadataUnavailable:
            pass
        credentials = await read_c2pa(image_bytes, image.content_type)
        if credentials.signed_at is not None:
            add(
                EvidenceKind.C2PA,
                credentials.signed_at,
                image.source_url,
                {"state": credentials.state.value, "signer": credentials.signer_issuer},
                confidence=Confidence.HIGH
                if credentials.state is C2PAState.VALID_TRUSTED
                else Confidence.LOW,
            )
        return found

    async def _store(
        self,
        ctx: StageContext,
        sighting_id: uuid.UUID,
        signals: list[
            tuple[EvidenceKind, datetime, BoundType, Confidence, str | None, dict[str, Any]]
        ],
    ) -> None:
        async with ctx.sessions.begin() as session:
            await session.execute(
                update(Sighting).where(Sighting.id == sighting_id).values(deciding_evidence_id=None)
            )
            await session.execute(
                delete(TimestampEvidence).where(TimestampEvidence.sighting_id == sighting_id)
            )
            rows: list[TimestampEvidence] = []
            for kind, value, bound, confidence, url, detail in signals:
                row = TimestampEvidence(
                    sighting_id=sighting_id,
                    kind=kind,
                    value=value,
                    bound=bound,
                    confidence=confidence,
                    source_url=url,
                    detail=detail,
                )
                session.add(row)
                rows.append(row)
            await session.flush()
            result = date_sighting(
                [Signal(str(r.id), r.kind, r.value, r.bound, r.confidence) for r in rows]
            )
            await session.execute(
                update(Sighting)
                .where(Sighting.id == sighting_id)
                .values(
                    date_lower=result.lower,
                    date_upper=result.upper,
                    date_confidence=result.confidence,
                    deciding_evidence_id=uuid.UUID(result.deciding.id) if result.deciding else None,
                    dating_rule_version=result.rule_version,
                )
            )
