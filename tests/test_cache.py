from hypr_vocal_command.llm.cache import CachedClassifier
from hypr_vocal_command.llm.client import ClassificationResult


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def classify(self, system_prompt: str, user_text: str) -> ClassificationResult:
        self.calls.append(user_text)
        return ClassificationResult(
            raw_response='{"intent": "OPEN_TERMINAL"}',
            latency_ms=1234.0,
            envelope={"intent": "OPEN_TERMINAL"},
        )

    def close(self) -> None:
        pass


def test_identical_text_skips_second_llm_call():
    client = _FakeClient()
    cache = CachedClassifier(client)

    cache.classify("sys", "open a terminal")
    cache.classify("sys", "open a terminal")

    assert client.calls == ["open a terminal"]


def test_case_and_whitespace_variants_hit_the_same_entry():
    client = _FakeClient()
    cache = CachedClassifier(client)

    cache.classify("sys", "Open A Terminal")
    cache.classify("sys", "  open   a terminal  ")

    assert client.calls == ["Open A Terminal"]


def test_cache_hit_returns_the_cached_envelope_with_near_zero_latency():
    client = _FakeClient()
    cache = CachedClassifier(client)

    cache.classify("sys", "open a terminal")
    result = cache.classify("sys", "open a terminal")

    assert result.envelope == {"intent": "OPEN_TERMINAL"}
    assert result.latency_ms == 0.0


def test_ttl_expiry_forces_a_fresh_call():
    client = _FakeClient()
    fake_time = [0.0]
    cache = CachedClassifier(client, ttl=10.0, timer=lambda: fake_time[0])

    cache.classify("sys", "open a terminal")
    fake_time[0] = 20.0  # advance past the 10s TTL
    cache.classify("sys", "open a terminal")

    assert client.calls == ["open a terminal", "open a terminal"]


def test_trailing_punctuation_variants_hit_the_same_entry():
    # Regression test: whisper doesn't deterministically add the same trailing punctuation
    # across two recordings of the same spoken phrase -- this must still be one cache entry.
    client = _FakeClient()
    cache = CachedClassifier(client)

    cache.classify("sys", "open a terminal.")
    cache.classify("sys", "open a terminal")

    assert client.calls == ["open a terminal."]


def test_different_text_does_not_share_a_cache_entry():
    client = _FakeClient()
    cache = CachedClassifier(client)

    cache.classify("sys", "open a terminal")
    cache.classify("sys", "open obsidian")

    assert client.calls == ["open a terminal", "open obsidian"]
