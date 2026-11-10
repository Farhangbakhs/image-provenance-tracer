"""Record and replay: recordings are faithful, redacted, verifiable and used offline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from origin_core.db.session import make_sessionmaker
from origin_core.enums import ProviderCallStatus
from origin_core.providers import quota
from origin_core.providers.base import ProviderError, RawResponse
from origin_core.providers.fixtures import REDACTED, FixtureStore, load, verify
from origin_core.providers.runner import ProviderRunner, RetryPolicy
from origin_core.settings import ProviderMode
from origin_core.storage import FilesystemBlobStore

from .support import ASSET, NOW, ScriptedAdapter, make_policy, no_sleep, used_units

pytestmark = pytest.mark.db

SECRET = "sk-live-0123456789"


def _runner(
    engine: AsyncEngine,
    tmp_path: Path,
    mode: ProviderMode,
    store: FixtureStore,
    policies: dict[str, quota.QuotaPolicy] | None = None,
) -> ProviderRunner:
    return ProviderRunner(
        sessions=make_sessionmaker(engine),
        blobs=FilesystemBlobStore(tmp_path / "blobs"),
        http=httpx.AsyncClient(),
        policies=policies or {},
        retry=RetryPolicy(attempts=1),
        clock=lambda: NOW,
        sleep=no_sleep,
        mode=mode,
        fixtures=store,
        redact_secrets=(SECRET,),
    )


def _response_with_secret() -> RawResponse:
    items = [{"page": "https://a.example", "image": "https://a.example/i.jpg"}]
    body = json.dumps(items) + f" <!-- echoed api_key={SECRET} -->"
    return RawResponse(body.encode(), units=1)


async def test_record_then_replay_offline(db_engine: AsyncEngine, tmp_path: Path) -> None:
    store = FixtureStore((tmp_path / "recordings",))
    policy = make_policy(5)
    recorder = ScriptedAdapter([_response_with_secret()], quota_key=policy.key)

    recorded = await _runner(
        db_engine, tmp_path, ProviderMode.RECORD, store, {policy.key: policy}
    ).run(recorder, ASSET)
    assert recorded.status is ProviderCallStatus.ERROR  # the comment makes it invalid JSON
    # Recording happens before parsing, so even an unparseable response is captured.
    path = tmp_path / "recordings" / recorder.name / f"{recorded.request_hash}.json"
    recording = load(path)
    assert SECRET not in path.read_text(encoding="utf-8")
    assert REDACTED in recording.body
    assert recording.synthetic is False
    assert recording.asset_sha256 == ASSET.sha256


async def test_replay_serves_recording_without_network_or_quota(
    db_engine: AsyncEngine, tmp_path: Path
) -> None:
    store = FixtureStore((tmp_path / "recordings",))
    policy = make_policy(5)
    body = json.dumps([{"page": "https://b.example", "image": "https://b.example/i.jpg"}])
    live = ScriptedAdapter([RawResponse(body.encode())], quota_key=policy.key)
    await _runner(db_engine, tmp_path, ProviderMode.RECORD, store, {policy.key: policy}).run(
        live, ASSET
    )
    assert await used_units(make_sessionmaker(db_engine), policy) == 1

    # Same provider name, but every scripted call would now fail: replay must not call it.
    offline = ScriptedAdapter(
        [ProviderError("network used", retryable=False)], quota_key=policy.key
    )
    offline.name = live.name
    replayed = await _runner(
        db_engine, tmp_path, ProviderMode.REPLAY, store, {policy.key: policy}
    ).run(offline, ASSET)

    assert replayed.status is ProviderCallStatus.REPLAYED
    assert [h.page_url for h in replayed.hits] == ["https://b.example"]
    assert offline.calls == 0
    assert await used_units(make_sessionmaker(db_engine), policy) == 1


async def test_replay_without_recording_fails_loudly(
    db_engine: AsyncEngine, tmp_path: Path
) -> None:
    store = FixtureStore((tmp_path / "recordings",))
    adapter = ScriptedAdapter([], quota_key="unmetered")
    outcome = await _runner(db_engine, tmp_path, ProviderMode.REPLAY, store).run(adapter, ASSET)
    assert outcome.status is ProviderCallStatus.ERROR
    assert outcome.error is not None and "no recording" in outcome.error
    assert adapter.calls == 0


def test_runner_refuses_replay_without_store(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="FixtureStore"):
        ProviderRunner(
            sessions=None,  # pyright: ignore[reportArgumentType]
            blobs=FilesystemBlobStore(tmp_path),
            http=httpx.AsyncClient(),
            policies={},
            mode=ProviderMode.REPLAY,
        )


def _write(store: FixtureStore, body: bytes = b"[]") -> Path:
    return store.write(
        provider="lens",
        rh=_rh(),
        asset_sha256=ASSET.sha256,
        params={"type": "exact"},
        body=body,
        content_type="application/json",
        units=1,
        recorded_at=datetime(2026, 11, 10, tzinfo=UTC),
    )


def _rh() -> str:
    from origin_core.hashing import request_hash

    return request_hash("lens", ASSET.sha256, {"type": "exact"})


def test_verify_accepts_valid_trees(tmp_path: Path) -> None:
    _write(FixtureStore((tmp_path / "recordings",)))
    assert verify(tmp_path / "recordings", tmp_path / "synthetic") == []


def test_verify_detects_tampered_body(tmp_path: Path) -> None:
    path = _write(FixtureStore((tmp_path / "recordings",)))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["body"] = '[{"page": "https://forged.example"}]'
    path.write_text(json.dumps(data), encoding="utf-8")
    [problem] = verify(tmp_path / "recordings", tmp_path / "synthetic")
    assert "body_sha256" in problem


def test_verify_requires_synthetic_label_in_synthetic_tree(tmp_path: Path) -> None:
    path = _write(FixtureStore((tmp_path / "synthetic",)))  # written as synthetic=false
    [problem] = verify(tmp_path / "recordings", tmp_path / "synthetic")
    assert "'synthetic' must be True" in problem
    assert path.exists()


def test_store_reads_recordings_before_synthetic(tmp_path: Path) -> None:
    real = FixtureStore((tmp_path / "recordings",))
    fake = FixtureStore((tmp_path / "synthetic",))
    _write(fake, b'["synthetic"]')
    _write(real, b'["real"]')
    both = FixtureStore((tmp_path / "recordings", tmp_path / "synthetic"))
    found = both.find("lens", _rh())
    assert found is not None and found.body == '["real"]'
