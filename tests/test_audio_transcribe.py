import httpx
import numpy as np
import pytest
import respx

from hypr_vocal_command.audio import transcribe as transcribe_module
from hypr_vocal_command.audio.transcribe import resolve_model_path, transcribe


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModel:
    def __init__(
        self,
        language: str,
        probability: float,
        segments: list[_FakeSegment],
        all_probs: dict[str, float] | None = None,
    ) -> None:
        self._language = language
        self._probability = probability
        self._segments = segments
        self._all_probs = all_probs if all_probs is not None else {language: probability}
        self.transcribe_kwargs: dict = {}
        self.auto_detect_language_calls = 0

    def auto_detect_language(self, media):
        self.auto_detect_language_calls += 1
        return (self._language, self._probability), self._all_probs

    def transcribe(self, media, **kwargs):
        self.transcribe_kwargs = kwargs
        return self._segments


def test_transcribe_joins_segments_and_strips_whitespace():
    model = _FakeModel(
        language="en",
        probability=0.97,
        segments=[_FakeSegment(" open "), _FakeSegment("a terminal ")],
    )
    audio = np.zeros(16000, dtype=np.int16)

    result = transcribe(model, audio)

    assert result.text == "open a terminal"
    assert result.language == "en"
    assert result.language_probability == 0.97
    assert model.transcribe_kwargs["language"] == "en"


def test_transcribe_handles_empty_segments():
    model = _FakeModel(language="en", probability=0.5, segments=[])
    result = transcribe(model, np.zeros(1600, dtype=np.int16))
    assert result.text == ""


def test_transcribe_restricts_language_to_allowed_set():
    # Regression test: real garbled short commands frequently "won" whisper's raw top-1
    # pick as an irrelevant language (Swedish, Turkish, Polish...) at low confidence.
    # The final choice must come from `allowed_languages` only, using the full
    # probability distribution we already compute -- never the unrestricted top pick.
    model = _FakeModel(
        language="sv",
        probability=0.42,
        segments=[_FakeSegment("hello")],
        all_probs={"sv": 0.42, "en": 0.31, "ar": 0.02, "tr": 0.10},
    )

    result = transcribe(model, np.zeros(16000, dtype=np.int16))

    assert result.language == "en"
    assert result.language_probability == 0.31
    assert result.raw_top_language == "sv"
    assert result.raw_top_probability == 0.42
    assert model.transcribe_kwargs["language"] == "en"


def test_transcribe_passes_initial_prompt_when_given():
    model = _FakeModel(language="en", probability=0.9, segments=[_FakeSegment("hi")])

    transcribe(model, np.zeros(1600, dtype=np.int16), initial_prompt="full screen. close this window.")

    assert model.transcribe_kwargs["initial_prompt"] == "full screen. close this window."


def test_transcribe_omits_initial_prompt_when_not_given():
    model = _FakeModel(language="en", probability=0.9, segments=[_FakeSegment("hi")])

    transcribe(model, np.zeros(1600, dtype=np.int16))

    assert "initial_prompt" not in model.transcribe_kwargs


def test_transcribe_collapses_repetition_loop_artifact():
    # Regression test: live testing hit a real whisper repetition-loop artifact -- the
    # same short sentence echoed 50+ times in one transcript. Must collapse to one copy
    # rather than passing 50 duplicate sentences on to the LLM classifier.
    repeated = " ".join(["close this tile."] * 55)
    model = _FakeModel(language="en", probability=0.31, segments=[_FakeSegment(repeated)])

    result = transcribe(model, np.zeros(16000, dtype=np.int16))

    assert result.text == "close this tile."


def test_transcribe_preserves_distinct_consecutive_sentences():
    model = _FakeModel(
        language="en", probability=0.9, segments=[_FakeSegment("Open a terminal. Then open obsidian.")]
    )

    result = transcribe(model, np.zeros(16000, dtype=np.int16))

    assert result.text == "Open a terminal. Then open obsidian."


def test_transcribe_skips_auto_detect_when_language_hint_given():
    # Regression test / optimization: auto_detect_language() roughly doubles whisper's
    # own encoder cost (measured in Phase 5) and its signal isn't consumed by any real
    # decision until Phase 9's hotkey-mismatch check exists. When the caller already
    # knows the pipeline's language (the only case reachable today), skip it entirely.
    model = _FakeModel(language="sv", probability=0.9, segments=[_FakeSegment("hi")])

    result = transcribe(model, np.zeros(1600, dtype=np.int16), language_hint="en")

    assert model.auto_detect_language_calls == 0
    assert result.language == "en"
    assert result.raw_top_language == "en"
    assert model.transcribe_kwargs["language"] == "en"


def test_resolve_model_path_uses_cache_without_any_network_call(monkeypatch, tmp_path):
    cached = tmp_path / "ggml-base.bin"
    cached.write_bytes(b"fake model")
    monkeypatch.setattr(transcribe_module, "_cache_path", lambda: cached)

    # No respx route registered at all -- any real HTTP attempt would error out.
    assert resolve_model_path() == cached


@respx.mock
def test_resolve_model_path_downloads_when_cache_missing(monkeypatch, tmp_path):
    cache_target = tmp_path / "models" / "ggml-base.bin"
    monkeypatch.setattr(transcribe_module, "_cache_path", lambda: cache_target)
    respx.get(transcribe_module._BASE_MODEL_URL).mock(
        return_value=httpx.Response(200, content=b"fake model bytes")
    )

    result = resolve_model_path()

    assert result == cache_target
    assert cache_target.read_bytes() == b"fake model bytes"


@respx.mock
def test_resolve_model_path_falls_back_to_tiny_when_download_fails(monkeypatch, tmp_path):
    cache_target = tmp_path / "models" / "ggml-base.bin"
    tiny = tmp_path / "ggml-tiny.bin"
    tiny.write_bytes(b"fake tiny model")
    monkeypatch.setattr(transcribe_module, "_cache_path", lambda: cache_target)
    monkeypatch.setattr(transcribe_module, "_tiny_fallback_path", lambda: tiny)
    respx.get(transcribe_module._BASE_MODEL_URL).mock(return_value=httpx.Response(500))

    assert resolve_model_path() == tiny


@respx.mock
def test_resolve_model_path_raises_if_download_fails_and_no_tiny_fallback(monkeypatch, tmp_path):
    cache_target = tmp_path / "models" / "ggml-base.bin"
    missing_tiny = tmp_path / "no-such-tiny.bin"
    monkeypatch.setattr(transcribe_module, "_cache_path", lambda: cache_target)
    monkeypatch.setattr(transcribe_module, "_tiny_fallback_path", lambda: missing_tiny)
    respx.get(transcribe_module._BASE_MODEL_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(FileNotFoundError):
        resolve_model_path()
