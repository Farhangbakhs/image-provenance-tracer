"""Anthropic Claude, optional: used only when ORIGIN_LLM_PROVIDER=anthropic and a key is set.

Calls go through the official `anthropic` SDK. Structured output uses the Messages API's
`output_config.format` (type `json_schema`), which guarantees the first text block is JSON
matching the schema. That schema format requires `additionalProperties: false` on every object
and does not accept length, count or numeric limits, so `strict_schema` sends a simplified copy;
ORIGIN's own Pydantic validation still enforces the full schema on every reply.

Defaults: model `claude-opus-5-5`, effort `low` (claim extraction and grouping are extraction
tasks), and server-side refusal fallbacks routed by refusal category (`fallbacks: "default"`),
so a policy decline is retried on a fallback model within the same call. A response that still
ends in `refusal` is reported as an error, never as an empty answer.
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast

import anthropic
import httpx
from anthropic.types.beta import BetaJSONOutputFormatParam, BetaOutputConfigParam

from origin_core.llm.base import LLMError, Prompt, RawReply

DEFAULT_MODEL = "claude-opus-5-5"
Effort = Literal["low", "medium", "high", "xhigh", "max"]
DEFAULT_EFFORT: Effort = "low"
MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_UNSUPPORTED_KEYS = {
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "title",
}


def strict_schema(schema: Any) -> Any:
    """A copy of `schema` in the form structured outputs accept.

    Every object gets `additionalProperties: false` and lists all its properties as required
    (optional fields stay nullable through their anyOf/null type); unsupported constraint
    keywords are dropped. The dropped constraints are still checked by Pydantic afterwards.
    """
    if isinstance(schema, list):
        return [strict_schema(item) for item in cast(list[Any], schema)]
    if not isinstance(schema, dict):
        return schema
    node = cast(dict[str, Any], schema)
    out: dict[str, Any] = {
        k: strict_schema(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS
    }
    out.pop("default", None)
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(cast(dict[str, Any], out["properties"]))
    return out


class AnthropicProvider:
    name: str = "anthropic"

    def __init__(
        self, api_key: str, model: str = DEFAULT_MODEL, effort: Effort = DEFAULT_EFFORT
    ) -> None:
        # The SDK retries 408/409/429/5xx and connection errors itself (twice by default);
        # anything still failing reaches the LLMRunner as an LLMError.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=300.0)
        self.model: str = model
        self._effort: Effort = effort

    async def complete(self, prompt: Prompt, client: httpx.AsyncClient) -> RawReply:
        output_format: BetaJSONOutputFormatParam = {
            "type": "json_schema",
            "schema": strict_schema(prompt.schema),
        }
        output_config: BetaOutputConfigParam = {"effort": self._effort, "format": output_format}
        try:
            response = await self._client.beta.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.user}],
                output_config=output_config,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMError(f"anthropic rate limited: {exc.message}", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500
            raise LLMError(
                f"anthropic HTTP {exc.status_code}: {exc.message}", retryable=retryable
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"anthropic connection failed: {exc}", retryable=True) from exc
        return RawReply(response.to_json().encode("utf-8"))

    def text(self, body: bytes) -> str:
        payload = cast(dict[str, Any], json.loads(body))
        stop = payload.get("stop_reason")
        if stop == "refusal":
            details = cast(dict[str, Any], payload.get("stop_details") or {})
            raise LLMError(
                f"anthropic declined the request (category {details.get('category')})",
                retryable=False,
            )
        if stop == "max_tokens":
            raise LLMError("anthropic reply was cut off at max_tokens", retryable=False)
        blocks = cast(list[dict[str, Any]], payload.get("content") or [])
        text = "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
        if not text:
            raise LLMError(f"anthropic returned no text (stop_reason {stop})", retryable=False)
        return text
