from __future__ import annotations

import pytest

from origin_core.providers.registry import build_providers
from origin_core.settings import Settings


def _settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # pyright: ignore[reportCallIssue, reportArgumentType]


def test_missing_keys_make_providers_unavailable_with_a_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("GOOGLE_VISION_API_KEY", "SERPAPI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    setup = build_providers(_settings())
    assert setup.adapters == []
    assert setup.unavailable == {
        "vision": "GOOGLE_VISION_API_KEY is not set",
        "lens": "SERPAPI_API_KEY is not set",
    }


def test_keys_enable_providers_and_are_marked_for_redaction() -> None:
    setup = build_providers(
        _settings(GOOGLE_VISION_API_KEY="gv-secret", SERPAPI_API_KEY="serp-secret")
    )
    assert [a.name for a in setup.adapters] == ["vision", "lens"]
    assert set(setup.secrets) == {"gv-secret", "serp-secret"}


def test_replay_mode_needs_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GOOGLE_VISION_API_KEY", "SERPAPI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ORIGIN_PROVIDER_MODE", "replay")
    monkeypatch.setenv("ORIGIN_PROVIDERS", '["vision","lens","yandex"]')
    setup = build_providers(_settings())
    assert [a.name for a in setup.adapters] == ["vision", "lens", "yandex"]
    assert setup.secrets == ()


def test_unknown_provider_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORIGIN_PROVIDERS", '["tineye"]')
    setup = build_providers(_settings())
    assert setup.unavailable == {"tineye": "unknown provider"}
