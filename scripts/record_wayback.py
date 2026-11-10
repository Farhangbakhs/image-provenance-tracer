"""Record real Wayback CDX responses as fixtures (network required).

    uv run python scripts/record_wayback.py URL [URL ...]

Each response is written to fixtures/recordings/wayback/<request_hash>.json, exactly as the
ProviderRunner would in record mode, so tests and demo mode can replay it offline.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from origin_core.hashing import request_hash
from origin_core.providers.base import UrlSubject
from origin_core.providers.fixtures import FixtureStore
from origin_core.providers.wayback import WaybackFirstCapture

ROOT = Path(__file__).resolve().parent.parent


async def main(urls: list[str]) -> None:
    adapter = WaybackFirstCapture()
    store = FixtureStore((ROOT / "fixtures" / "recordings",))
    async with httpx.AsyncClient() as client:
        for url in urls:
            subject = UrlSubject(url)
            raw = await adapter.fetch(subject, client)
            path = store.write(
                provider=adapter.name,
                rh=request_hash(adapter.name, subject.sha256, adapter.params()),
                asset_sha256=subject.sha256,
                params=adapter.params(),
                body=raw.body,
                content_type=raw.content_type,
                units=raw.units,
                recorded_at=datetime.now(UTC),
            )
            hits = adapter.parse(raw.body)
            print(f"{url}: {len(hits)} capture(s) -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
