"""Ollama /api/chat client for grammar-constrained structured intent classification.

Uses a single call with the full discriminated-union schema as `format` (Plan A from the
project plan's Cross-Cutting Decision 9) — confirmed empirically against qwen2.5:7b to
produce reliably valid, correctly-tagged output, provided `intent`/`schema_version` are
marked as *required* fields in the schema (see schema.py) so the GBNF grammar can't omit
them.
"""

import json
import time
from dataclasses import dataclass
from typing import Any, Self

import httpx

from ..schema import envelope_json_schema


@dataclass(frozen=True)
class ClassificationResult:
    raw_response: str
    latency_ms: float
    envelope: dict[str, Any]


class OllamaClient:
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        seed: int = 42,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._seed = seed
        self._client = httpx.Client(timeout=timeout)

    def classify(self, system_prompt: str, user_text: str) -> ClassificationResult:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "format": envelope_json_schema(),
            "stream": False,
            "options": {"temperature": 0, "seed": self._seed},
            "keep_alive": -1,
        }
        start = time.monotonic()
        response = self._client.post(f"{self._base_url}/api/chat", json=payload)
        latency_ms = (time.monotonic() - start) * 1000
        response.raise_for_status()

        content = response.json()["message"]["content"]
        # schema_version isn't part of the schema the LLM generates against (see
        # envelope_json_schema()) -- injected here, before parse_envelope()'s full
        # validation (which does require it) ever sees this dict. raw_response is left
        # untouched -- it stays the model's true raw output, for telemetry integrity.
        envelope = json.loads(content)
        envelope.setdefault("schema_version", 1)
        return ClassificationResult(raw_response=content, latency_ms=latency_ms, envelope=envelope)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
