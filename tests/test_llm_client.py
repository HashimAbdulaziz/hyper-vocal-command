import json

import httpx
import pytest
import respx

from hypr_vocal_command import handlers  # noqa: F401  (populates the registry, needed for schema)
from hypr_vocal_command.llm.client import OllamaClient


@respx.mock
def test_classify_posts_expected_payload_and_parses_response():
    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": 1,
                            "intent": "OPEN_TERMINAL",
                            "confidence": 0.95,
                            "args": {},
                        }
                    )
                }
            },
        )

    respx.post("http://localhost:11434/api/chat").mock(side_effect=_handler)

    client = OllamaClient(model="qwen2.5:7b", base_url="http://localhost:11434")
    result = client.classify("system prompt", "open a terminal")

    sent = captured["json"]
    assert sent["model"] == "qwen2.5:7b"
    assert sent["stream"] is False
    assert sent["options"]["temperature"] == 0
    assert sent["keep_alive"] == -1
    assert "format" in sent
    assert sent["messages"][0] == {"role": "system", "content": "system prompt"}
    assert sent["messages"][1] == {"role": "user", "content": "open a terminal"}

    assert result.envelope["intent"] == "OPEN_TERMINAL"
    assert result.latency_ms >= 0


@respx.mock
def test_classify_raises_on_http_error():
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(500, text="internal error")
    )

    client = OllamaClient(model="qwen2.5:7b", base_url="http://localhost:11434")

    with pytest.raises(httpx.HTTPStatusError):
        client.classify("system prompt", "open a terminal")


@respx.mock
def test_classify_schema_marks_intent_required_and_omits_schema_version():
    # Regression guard for the Phase 3 finding: if `intent` isn't required, Ollama's
    # grammar can (and empirically does) omit or scramble it.
    #
    # schema_version is deliberately absent from this schema entirely (not just
    # optional) -- it's a constant the LLM can't usefully reason about, and asking it to
    # generate one costs real tokens (measured ~40-55ms/token on this hardware) for zero
    # classification value. It's injected by the client after parsing instead (see
    # test_classify_injects_schema_version_into_the_envelope below).
    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {"intent": "UNRECOGNIZED", "confidence": 0.5, "args": {}}
                    )
                }
            },
        )

    respx.post("http://localhost:11434/api/chat").mock(side_effect=_handler)

    client = OllamaClient(model="qwen2.5:7b", base_url="http://localhost:11434")
    client.classify("system prompt", "anything")

    schema = captured["json"]["format"]
    for variant in schema["$defs"].values():
        if "intent" in variant.get("properties", {}):
            assert "intent" in variant["required"]
            assert "schema_version" not in variant["properties"]


@respx.mock
def test_classify_injects_schema_version_into_the_envelope():
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {"intent": "UNRECOGNIZED", "confidence": 0.5, "args": {}}
                    )
                }
            },
        )
    )

    client = OllamaClient(model="qwen2.5:7b", base_url="http://localhost:11434")
    result = client.classify("system prompt", "anything")

    assert result.envelope["schema_version"] == 1
    # raw_response is untouched -- the model's true raw output, for telemetry integrity.
    assert "schema_version" not in result.raw_response
