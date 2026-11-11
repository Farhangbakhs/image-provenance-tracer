"""Google Gemini through the Gemini API's generateContent endpoint, with JSON-schema output.

Verified on 2026-11-11 with a real key: generateContent accepts generationConfig
{responseMimeType: "application/json", responseJsonSchema: {...}} and returns the JSON text in
candidates[0].content.parts[].text. gemini-2.5-flash is no longer offered to new users; on the
free tier gemini-3.5-flash-lite answered in ~6 s, gemini-3.8-flash in 86-131 s. Free-tier
prompts and outputs may be used by Google to improve its products (PLAN.md 1.1).

Docs: https://aistudio.google.com/docs/pricing, https://aistudio.google.com/docs/structured-output
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx

from origin_core.llm.base import LLMError, Prompt, RawReply

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


class GeminiProvider:
    name: str = "gemini"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self.model: str = model

    async def complete(self, prompt: Prompt, client: httpx.AsyncClient) -> RawReply:
        body = {
            "systemInstruction": {"parts": [{"text": prompt.system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt.user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": prompt.schema,
            },
        }
        try:
            response = await client.post(
                ENDPOINT.format(model=self.model),
                headers={"x-goog-api-key": self._api_key},
                json=body,
                timeout=180,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"gemini request failed: {exc!r}", retryable=True) from exc
        if response.status_code in (429, 500, 502, 503, 504):
            raise LLMError(f"gemini HTTP {response.status_code}", retryable=True)
        if response.status_code != 200:
            raise LLMError(
                f"gemini HTTP {response.status_code}: {response.text[:300]}", retryable=False
            )
        return RawReply(response.content)

    def text(self, body: bytes) -> str:
        payload = cast(dict[str, Any], json.loads(body))
        candidates = cast(list[dict[str, Any]], payload.get("candidates") or [])
        if not candidates:
            feedback = payload.get("promptFeedback")
            raise LLMError(f"gemini returned no candidates ({feedback})", retryable=False)
        first = candidates[0]
        reason = first.get("finishReason")
        parts = cast(list[dict[str, Any]], (first.get("content") or {}).get("parts") or [])
        text = "".join(str(p.get("text", "")) for p in parts if not p.get("thought"))
        if not text:
            raise LLMError(f"gemini returned no text (finishReason {reason})", retryable=False)
        return text
