import pytest
from pydantic import ValidationError

from origin_core.settings import Settings


def _settings() -> Settings:
    return Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_production_refuses_unofficial_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORIGIN_ENV", "production")
    monkeypatch.setenv("ORIGIN_ENABLE_UNOFFICIAL_PROVIDERS", "true")
    with pytest.raises(ValidationError, match="must be false"):
        _settings()
