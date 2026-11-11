"""The optional Claude provider: strict schemas, refusal handling and the request it sends."""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest

from origin_core.llm.base import LLMError, Prompt
from origin_core.llm.claude import FALLBACK_BETA, AnthropicProvider, strict_schema
from origin_core.llm.prompts import claim as claim_prompt
from origin_core.llm.prompts import narrative as narrative_prompt


def _objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        mapping = cast(dict[str, Any], node)
        if mapping.get("type") == "object" and "properties" in mapping:
            found.append(mapping)
        for value in mapping.values():
            found.extend(_objects(value))
    elif isinstance(node, list):
        for value in cast(list[Any], node):
            found.extend(_objects(value))
    return found


@pytest.mark.parametrize("schema", [claim_prompt.SCHEMA, narrative_prompt.SCHEMA])
def test_strict_schema_closes_every_object_and_drops_limits(schema: dict[str, Any]) -> None:
    strict = strict_schema(schema)
    text = json.dumps(strict)
    for forbidden in ('"maxLength"', '"minItems"', '"pattern"', '"title"', '"default"'):
        assert forbidden not in text
    objects = _objects(strict)
    assert objects
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])
    assert schema != strict  # the original is untouched


def _body(**over: Any) -> bytes:
    payload: dict[str, Any] = {
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": '{"has_claim": false}'},
        ],
    }
    payload.update(over)
    return json.dumps(payload).encode()


def test_text_takes_only_text_blocks() -> None:
    assert AnthropicProvider("k").text(_body()) == '{"has_claim": false}'


def test_refusals_and_truncation_are_errors_not_empty_answers() -> None:
    provider = AnthropicProvider("k")
    with pytest.raises(LLMError, match="declined") as refused:
        provider.text(_body(stop_reason="refusal", stop_details={"category": "cyber"}, content=[]))
    assert not refused.value.retryable
    with pytest.raises(LLMError, match="max_tokens"):
        provider.text(_body(stop_reason="max_tokens"))


async def test_request_uses_structured_output_effort_and_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AnthropicProvider("k")
    sent: dict[str, Any] = {}

    class FakeMessage:
        def to_json(self) -> str:
            return _body().decode()

    async def create(**kwargs: Any) -> FakeMessage:
        sent.update(kwargs)
        return FakeMessage()

    monkeypatch.setattr(provider._client.beta.messages, "create", create)  # pyright: ignore[reportPrivateUsage]
    prompt = Prompt("claim.v1", "system text", "user text", claim_prompt.SCHEMA)
    async with httpx.AsyncClient() as client:
        raw = await provider.complete(prompt, client)
    assert provider.text(raw.body) == '{"has_claim": false}'
    assert sent["model"] == "claude-opus-5-5"
    assert sent["system"] == "system text"
    assert sent["messages"] == [{"role": "user", "content": "user text"}]
    assert sent["output_config"]["effort"] == "low"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert sent["betas"] == [FALLBACK_BETA] and sent["fallbacks"] == "default"
