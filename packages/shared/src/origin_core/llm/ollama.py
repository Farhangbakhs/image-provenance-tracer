"""A local model through Ollama's chat API: fully private and offline.

Ollama accepts a JSON schema in the `format` field of /api/chat and returns the model's text in
message.content. Docs: https://github.com/ollama/ollama/blob/main/docs/api.md
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx

from origin_core.llm.base import LLMError, Prompt, RawReply

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"


class OllamaProvider:
    name: str = "ollama"

    def __init__(self, base_url: str = DEFAULT_URL, model: str = DEFAULT_MODEL) -> None:
        self._url = base_url.rstrip("/")
        self.model: str = model

    async def complete(self, prompt: Prompt, client: httpx.AsyncClient) -> RawReply:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "format": prompt.schema,
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            response = await client.post(f"{self._url}/api/chat", json=body, timeout=600)
        except httpx.ConnectError as exc:
            raise LLMError(f"ollama is not reachable at {self._url}", retryable=False) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama request failed: {exc!r}", retryable=True) from exc
        if response.status_code != 200:
            raise LLMError(
                f"ollama HTTP {response.status_code}: {response.text[:300]}", retryable=False
            )
        return RawReply(response.content)

    def text(self, body: bytes) -> str:
        payload = cast(dict[str, Any], json.loads(body))
        message = cast(dict[str, Any], payload.get("message") or {})
        content = message.get("content")
        if not isinstance(content, str) or not content:
            raise LLMError("ollama returned no message content", retryable=False)
        return content
