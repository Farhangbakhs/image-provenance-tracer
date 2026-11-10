import pytest
from pydantic import ValidationError

from origin_core.settings import Environment, ProviderMode, Settings


def _settings() -> Settings:
    return Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_production_refuses_unofficial_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORIGIN_ENV", "production")
    monkeypatch.setenv("ORIGIN_ENABLE_UNOFFICIAL_PROVIDERS", "true")
    with pytest.raises(ValidationError, match="must be false"):
        _settings()


def test_demo_requires_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORIGIN_ENV", "demo")
    monkeypatch.setenv("ORIGIN_PROVIDER_MODE", "live")
    with pytest.raises(ValidationError, match="replay"):
        _settings()


def test_demo_with_replay_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORIGIN_ENV", "demo")
    monkeypatch.setenv("ORIGIN_PROVIDER_MODE", "replay")
    settings = _settings()
    assert settings.env is Environment.DEMO
    assert settings.provider_mode is ProviderMode.REPLAY
