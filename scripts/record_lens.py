"""Record a real Google Lens (SerpApi) exact-matches response as a fixture (network and key).

    SERPAPI_API_KEY=... uv run python scripts/record_lens.py IMAGE [IMAGE ...]
    SERPAPI_KEY_FILE=path/to/key.txt uv run python scripts/record_lens.py IMAGE [IMAGE ...]

A key file may hold the key alone or with a label; the 64-character hex key is taken from it.

Each query spends one search of the SerpApi free plan (the upload is not billed). The response is
written to fixtures/recordings/lens/<request_hash>.json with the key redacted, exactly as the
ProviderRunner would in record mode, so tests and demo mode can replay it offline.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from PIL import Image

from origin_core.hashing import request_hash, sha256_hex
from origin_core.providers.base import AssetRef
from origin_core.providers.fixtures import FixtureStore
from origin_core.providers.serpapi import LensExactMatches

ROOT = Path(__file__).resolve().parent.parent


def api_key() -> str:
    key = os.environ.get("SERPAPI_API_KEY", "").strip()
    key_file = os.environ.get("SERPAPI_KEY_FILE", "")
    if not key and key_file:
        found = re.findall(r"\b[0-9a-f]{64}\b", Path(key_file).read_text(encoding="utf-8"))
        key = found[0] if len(found) == 1 else ""
    if not key:
        raise SystemExit("set SERPAPI_API_KEY, or SERPAPI_KEY_FILE to a file holding one key")
    return key


def subject_for(path: str) -> AssetRef:
    data = Path(path).read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        content_type = Image.MIME.get(image.format or "", "application/octet-stream")
    return AssetRef(
        id=str(uuid.uuid4()),
        sha256=sha256_hex(data),
        content_type=content_type,
        data=data,
        width=width,
        height=height,
    )


async def main(paths: list[str]) -> None:
    key = api_key()
    adapter = LensExactMatches(key)
    store = FixtureStore((ROOT / "fixtures" / "recordings",))
    subjects = [(name, subject_for(name)) for name in paths]
    async with httpx.AsyncClient() as client:
        for name, subject in subjects:
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
                secrets=(key,),
            )
            hits = adapter.parse(raw.body)
            print(f"{name}: {len(hits)} exact match(es) -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
