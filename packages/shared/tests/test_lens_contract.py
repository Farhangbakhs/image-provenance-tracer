"""Lens contract test: the adapter against a real SerpApi response, replayed offline.

The recording is a live google_lens exact-matches query for the NASA Apollo 8 "Earthrise"
photograph (public domain, fixtures/queries/earthrise.jpg), made with scripts/record_lens.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from origin_core.hashing import request_hash, sha256_hex
from origin_core.providers.fixtures import FixtureStore
from origin_core.providers.serpapi import LensExactMatches

ROOT = Path(__file__).resolve().parents[3]
QUERY = ROOT / "fixtures" / "queries" / "earthrise.jpg"


def _recording() -> bytes:
    adapter = LensExactMatches("unused")
    asset_sha = sha256_hex(QUERY.read_bytes())
    rh = request_hash(adapter.name, asset_sha, adapter.params())
    recording = FixtureStore((ROOT / "fixtures" / "recordings",)).find(adapter.name, rh)
    assert recording is not None, "the Earthrise Lens recording is missing"
    assert recording.synthetic is False
    assert recording.asset_sha256 == asset_sha
    return recording.body_bytes()


def test_recorded_response_has_the_documented_shape() -> None:
    payload = json.loads(_recording())
    assert payload["search_metadata"]["status"] == "Success"
    assert payload["search_parameters"]["engine"] == "google_lens"
    assert payload["search_parameters"]["type"] == "exact_matches"
    item = payload["exact_matches"][0]
    assert {"position", "title", "link", "source", "thumbnail"} <= item.keys()


def test_recording_carries_no_key() -> None:
    payload = json.loads(_recording())
    assert "api_key" not in payload["search_parameters"]
    assert "api_key=" not in json.dumps(payload["search_metadata"])


def test_adapter_parses_every_exact_match_as_a_page_candidate() -> None:
    body = _recording()
    hits = LensExactMatches("unused").parse(body)
    items = json.loads(body)["exact_matches"]
    assert len(hits) == len(items) > 100
    assert all(h.page_url and h.page_url.startswith("http") for h in hits)
    assert all(h.image_url is None for h in hits)
    assert [h.rank for h in hits[:3]] == [1, 2, 3]


def test_lens_dates_parse_on_real_data() -> None:
    body = _recording()
    hits = LensExactMatches("unused").parse(body)
    shown = [i["date"] for i in json.loads(body)["exact_matches"] if i.get("date")]
    dated = [h.provider_date for h in hits if h.provider_date]
    # Relative dates ("9 days ago") are left unparsed; absolute ones all parse.
    relative = [d for d in shown if d.endswith("ago")]
    assert len(dated) == len(shown) - len(relative)
    assert min(dated) < datetime(2010, 1, 1, tzinfo=UTC)
