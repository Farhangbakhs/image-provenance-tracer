"""Cases, uploads and the asset panel's data, through the real API."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
from PIL import Image
from redis.asyncio import Redis

from origin_core.pipeline.jobs import run_job_id

pytestmark = [pytest.mark.db, pytest.mark.redis]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"


def _jpeg(width: int = 320, height: int = 240) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(out, format="JPEG", quality=90)
    return out.getvalue()


async def _case(client: httpx.AsyncClient, title: str = "Flood photo") -> str:
    response = await client.post("/cases", json={"title": title, "notes": "from a tip-off"})
    assert response.status_code == 201
    return str(response.json()["id"])


async def _upload(
    client: httpx.AsyncClient, case_id: str, data: bytes, name: str = "photo.jpg"
) -> httpx.Response:
    return await client.post(
        f"/cases/{case_id}/assets", files={"file": (name, data, "application/octet-stream")}
    )


async def test_create_list_and_get_case(client: httpx.AsyncClient) -> None:
    case_id = await _case(client, "Bridge collapse")
    listed = (await client.get("/cases")).json()
    assert any(c["id"] == case_id and c["title"] == "Bridge collapse" for c in listed)
    fetched = (await client.get(f"/cases/{case_id}")).json()
    assert fetched["notes"] == "from a tip-off" and fetched["assets"] == []
    assert (await client.post("/cases", json={"title": ""})).status_code == 422


async def test_upload_returns_the_asset_panel(
    client: httpx.AsyncClient, exiftool_available: bool
) -> None:
    case_id = await _case(client)
    response = await _upload(client, case_id, (FIXTURES / "no-manifest.jpg").read_bytes(), "A.jpg")
    assert response.status_code == 201
    asset = response.json()

    assert (asset["width"], asset["height"]) == (1024, 683)
    assert asset["original_filename"] == "A.jpg"
    assert asset["content_type"] == "image/jpeg"
    assert len(asset["fingerprints"]["sha256"]) == 64 and len(asset["fingerprints"]["pdq"]) == 64
    assert asset["credentials"]["state"] == "none"
    assert asset["credentials"]["trust_list"].startswith("c2pa-trust-list@")
    assert asset["embedding"] == {"status": "pending", "model": None}
    if exiftool_available:
        assert asset["metadata"]["status"] == "ok"
        assert asset["metadata"]["tag_count"] > 0

    display = await client.get(asset["display_url"])
    assert display.status_code == 200
    assert display.headers["content-type"] == "image/jpeg"
    assert display.headers["x-content-type-options"] == "nosniff"

    case = (await client.get(f"/cases/{case_id}")).json()
    assert [a["id"] for a in case["assets"]] == [asset["id"]]


async def test_signed_upload_reports_untrusted_credentials(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    data = (FIXTURES / "signed-test-cert.jpg").read_bytes()
    asset = (await _upload(client, case_id, data, "C.jpg")).json()

    credentials = asset["credentials"]
    assert credentials["state"] == "present_untrusted"
    assert credentials["validation_state"] == "Valid"
    assert "signingCredential.untrusted" in credentials["failures"]
    assert credentials["signed_at"] == "2023-09-29T17:40:14Z"

    evidence = (await client.get(f"/assets/{asset['id']}/evidence")).json()
    assert evidence["c2pa_manifest_store"]["active_manifest"]


async def test_identical_upload_returns_existing_asset(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    first = await _upload(client, case_id, _jpeg())
    again = await _upload(client, case_id, _jpeg(), "renamed.jpg")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]


async def test_unsupported_and_missing_case_are_refused(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    rejected = await _upload(client, case_id, b"%PDF-1.7 a document", "evil.jpg")
    assert rejected.status_code == 422
    assert rejected.json()["reason"] == "unsupported_format"
    missing = await _upload(client, "00000000-0000-0000-0000-000000000000", _jpeg())
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "upload_limits",
    [
        {
            "ORIGIN_UPLOAD_MAX_BYTES": 2_000,
            "ORIGIN_UPLOAD_MAX_PIXELS": 50_000_000,
            "ORIGIN_RATE_LIMIT_UPLOADS": 0,
            "ORIGIN_RATE_LIMIT_RUNS": 0,
        }
    ],
)
async def test_oversized_upload_is_413(client: httpx.AsyncClient) -> None:
    case_id = await _case(client)
    response = await _upload(client, case_id, _jpeg(800, 600))
    assert response.status_code == 413
    assert response.json()["reason"] == "too_large"


async def test_start_run_queues_a_job(client: httpx.AsyncClient, redis: Redis) -> None:
    case_id = await _case(client)
    asset = (await _upload(client, case_id, _jpeg())).json()
    response = await client.post(f"/assets/{asset['id']}/runs")
    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "queued"
    assert run["asset_id"] == asset["id"]
    import uuid

    assert await redis.exists(f"arq:job:{run_job_id(uuid.UUID(run['id']))}")  # pyright: ignore[reportUnknownMemberType]
    panel = (await client.get(f"/assets/{asset['id']}")).json()
    assert [r["id"] for r in panel["runs"]] == [run["id"]]


@pytest.mark.parametrize(
    "upload_limits",
    [
        {
            "ORIGIN_UPLOAD_MAX_BYTES": 20_000_000,
            "ORIGIN_UPLOAD_MAX_PIXELS": 50_000_000,
            "ORIGIN_RATE_LIMIT_UPLOADS": 0,
            "ORIGIN_RATE_LIMIT_RUNS": 2,
        }
    ],
)
async def test_run_starts_are_rate_limited(client: httpx.AsyncClient, redis: Redis) -> None:
    async for key in redis.scan_iter("ratelimit:run:*"):  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        await redis.delete(key)  # pyright: ignore[reportUnknownArgumentType]
    case_id = await _case(client)
    asset = (await _upload(client, case_id, _jpeg())).json()
    codes = [(await client.post(f"/assets/{asset['id']}/runs")).status_code for _ in range(3)]
    # The third may land in a new minute window; at least the first two pass.
    assert codes[:2] == [202, 202]
    if codes[2] == 429:
        refused = await client.post(f"/assets/{asset['id']}/runs")
        assert refused.status_code == 429
        assert 1 <= int(refused.headers["retry-after"]) <= 60
        assert "2 per minute" in refused.json()["detail"]
