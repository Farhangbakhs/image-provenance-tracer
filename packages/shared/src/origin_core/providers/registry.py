"""Which reverse-image providers a run uses, and why any requested one is unavailable."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from origin_core.providers.base import AssetRef, ProviderAdapter
from origin_core.providers.serpapi import LensExactMatches, YandexImages
from origin_core.providers.telegram import TelegramIndex
from origin_core.providers.vision import VisionWebDetection
from origin_core.settings import ProviderMode, Settings

KNOWN = ("vision", "lens", "yandex", "telegram")
REPLAY_KEY = "replay-mode-no-key"


@dataclass(frozen=True)
class ProviderSetup:
    adapters: list[ProviderAdapter[AssetRef]]
    #: Requested providers that cannot run, with the reason shown to the analyst.
    unavailable: dict[str, str] = field(default_factory=dict[str, str])
    #: Values to redact from anything recorded.
    secrets: tuple[str, ...] = ()


def build_providers(
    settings: Settings, sessions: async_sessionmaker[AsyncSession] | None = None
) -> ProviderSetup:
    """The adapters for a trace. With ORIGIN_ENABLE_TELEGRAM, the Telegram index is added."""
    replay = settings.provider_mode is ProviderMode.REPLAY
    vision_key = (
        settings.google_vision_api_key.get_secret_value()
        if settings.google_vision_api_key
        else None
    )
    serp_key = settings.serpapi_api_key.get_secret_value() if settings.serpapi_api_key else None

    adapters: list[ProviderAdapter[AssetRef]] = []
    unavailable: dict[str, str] = {}
    requested = list(settings.providers)
    if settings.enable_telegram and "telegram" not in requested:
        requested.append("telegram")
    for name in requested:
        if name not in KNOWN:
            unavailable[name] = "unknown provider"
        elif name == "telegram":
            if not settings.enable_telegram:
                unavailable[name] = "ORIGIN_ENABLE_TELEGRAM is off (see PLAN.md 1.9)"
            elif sessions is None:
                unavailable[name] = "the Telegram index needs the database"
            else:
                adapters.append(TelegramIndex(sessions))
        elif name == "vision":
            if vision_key or replay:
                adapters.append(VisionWebDetection(vision_key or REPLAY_KEY))
            else:
                unavailable[name] = "GOOGLE_VISION_API_KEY is not set"
        elif not (serp_key or replay):
            unavailable[name] = "SERPAPI_API_KEY is not set"
        elif name == "lens":
            adapters.append(LensExactMatches(serp_key or REPLAY_KEY))
        else:
            adapters.append(YandexImages(serp_key or REPLAY_KEY))
    secrets = tuple(k for k in (vision_key, serp_key) if k)
    return ProviderSetup(adapters=adapters, unavailable=unavailable, secrets=secrets)
