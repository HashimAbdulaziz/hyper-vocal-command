"""Normalized-text LRU/TTL cache in front of OllamaClient.classify(), so repeated identical
utterances skip the LLM round-trip entirely. A cache hit returns the exact same envelope a
fresh call would have -- it is still validated and gated in executor.execute() exactly like
any other classification result; this only shortcuts the network/inference call itself.
"""

import time
from collections.abc import Callable
from typing import Self

from cachetools import TTLCache

from ..config import normalize_text
from .client import ClassificationResult, OllamaClient


class CachedClassifier:
    def __init__(
        self,
        client: OllamaClient,
        maxsize: int = 256,
        ttl: float = 300.0,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl, timer=timer)

    def classify(self, system_prompt: str, user_text: str) -> ClassificationResult:
        key = normalize_text(user_text)

        cached = self._cache.get(key)
        if cached is not None:
            return ClassificationResult(
                raw_response=cached.raw_response,
                latency_ms=0.0,
                envelope=cached.envelope,
            )

        result = self._client.classify(system_prompt, user_text)
        self._cache[key] = result
        return result

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
