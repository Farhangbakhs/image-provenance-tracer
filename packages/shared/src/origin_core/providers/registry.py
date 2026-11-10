"""Which reverse-image providers a run uses, and why any requested one is unavailable."""

from __future__ import annotations

from dataclasses import dataclass, field

from origin_core.providers.base import AssetRef, ProviderAdapter
from origin_core.providers.serpapi import LensExactMatches, YandexImages
from origin_core.providers.vision import VisionWebDetection
from origin_core.settings import ProviderMode, Settings

KNOWN = ("vision", "lens", "yandex")
REPLAY_KEY = "replay-mode-no-key"


@dataclass(frozen=True)
class ProviderSetup:
    adapters: list[ProviderAdapter[AssetRef]]
    #: Requested providers that cannot run, with the reason shown to the analyst.
    unavailable: dict[str, str] = field(default_factory=dict[str, str])
    #: Values to redact from anything recorded.
    secrets: tuple[str, ...] = ()


def build_providers(settings: Settings) -> ProviderSetup:
    replay = settings.provider_mode is ProviderMode.REPLAY
    vision_key = (
        settings.google_vision_api_key.get_secret_value()
        if settings.google_vision_api_key
        else None
    )
    serp_key = settings.serpapi_api_key.get_secret_value() if settings.serpapi_api_key else None

    adapters: list[ProviderAdapter[AssetRef]] = []
    unavailable: dict[str, str] = {}
    for name in settings.providers:
        if name not in KNOWN:
            unavailable[name] = "unknown provider"
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
