"""Which language model a run uses, or why none is available."""

from __future__ import annotations

from dataclasses import dataclass

from origin_core.llm.base import LLMProvider
from origin_core.llm.claude import AnthropicProvider
from origin_core.llm.gemini import GeminiProvider
from origin_core.llm.ollama import OllamaProvider
from origin_core.settings import ProviderMode, Settings

REPLAY_KEY = "replay-mode-no-key"


@dataclass(frozen=True)
class LLMSetup:
    provider: LLMProvider | None
    #: Why no provider is available, shown to the analyst.
    unavailable: str | None = None
    secrets: tuple[str, ...] = ()


def build_llm(settings: Settings) -> LLMSetup:
    replay = settings.provider_mode is ProviderMode.REPLAY
    choice = settings.llm_provider
    if choice == "gemini":
        key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        if not key and not replay:
            return LLMSetup(None, "GEMINI_API_KEY is not set")
        return LLMSetup(
            GeminiProvider(key or REPLAY_KEY, settings.gemini_model),
            secrets=(key,) if key else (),
        )
    if choice == "ollama":
        return LLMSetup(OllamaProvider(settings.ollama_url, settings.ollama_model))
    if choice == "anthropic":
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        if not key and not replay:
            return LLMSetup(None, "ANTHROPIC_API_KEY is not set")
        return LLMSetup(
            AnthropicProvider(key or REPLAY_KEY, settings.anthropic_model),
            secrets=(key,) if key else (),
        )
    return LLMSetup(None, f"unknown LLM provider '{choice}'")
