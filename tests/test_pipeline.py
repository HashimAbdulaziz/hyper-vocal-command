from dataclasses import dataclass

import httpx
import numpy as np
import pytest

from hypr_vocal_command import handlers  # noqa: F401  (populates the registry)
from hypr_vocal_command.config import Config
from hypr_vocal_command.llm.client import ClassificationResult
from hypr_vocal_command.pipeline import run_pipeline
from hypr_vocal_command.registry import ExecutionResult


@dataclass
class _FakeTranscription:
    text: str
    language: str = "en"
    language_probability: float = 1.0
    raw_top_language: str = "en"
    raw_top_probability: float = 1.0


class _FakeClassifier:
    def __init__(self, result=None, error=None) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[str, str]] = []

    def classify(self, system_prompt: str, text: str) -> ClassificationResult:
        self.calls.append((system_prompt, text))
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch, tmp_path):
    monkeypatch.setattr("hypr_vocal_command.pipeline.notify", lambda *a, **k: None)
    monkeypatch.setattr("hypr_vocal_command.utils.telemetry._state_dir", lambda: tmp_path)


def _kwargs(**overrides):
    base = {
        "vad": object(),
        "whisper_model": object(),
        "classifier": _FakeClassifier(),
        "system_prompt": "system prompt",
        "vocabulary_prompt": "vocab",
        "config": Config(),
        "language": "en",
    }
    base.update(overrides)
    return base


def test_no_speech_detected_short_circuits(monkeypatch):
    monkeypatch.setattr("hypr_vocal_command.pipeline.record_utterance", lambda vad, cfg: None)

    result = run_pipeline(**_kwargs())

    assert result.ok is False
    assert result.message == "No speech detected."
    assert result.transcript == ""
    assert result.transcribe_ms == 0.0
    assert result.llm_latency_ms == 0.0


def test_empty_transcript_short_circuits(monkeypatch):
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.record_utterance",
        lambda vad, cfg: np.zeros(1600, dtype=np.int16),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.transcribe",
        lambda *a, **k: _FakeTranscription(text=""),
    )

    result = run_pipeline(**_kwargs())

    assert result.ok is False
    assert result.message == "Empty transcript, nothing to classify."
    assert result.transcribe_ms > 0


def test_llm_http_error_is_caught_and_reported(monkeypatch):
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.record_utterance",
        lambda vad, cfg: np.zeros(1600, dtype=np.int16),
    )
    # Deliberately not "open a terminal" -- fastpath.py now matches that deterministically
    # and would never reach the classifier at all, defeating this test's purpose.
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.transcribe",
        lambda *a, **k: _FakeTranscription(text="do the special thing"),
    )
    classifier = _FakeClassifier(error=httpx.ConnectError("connection refused"))

    result = run_pipeline(**_kwargs(classifier=classifier))

    assert result.ok is False
    assert "LLM request failed" in result.message
    assert result.transcript == "do the special thing"


def test_full_success_path_executes_and_reports_all_fields(monkeypatch):
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.record_utterance",
        lambda vad, cfg: np.zeros(1600, dtype=np.int16),
    )
    # See the comment above -- must be a phrase fastpath.py defers on, so this test
    # actually exercises the classifier/execute wiring rather than short-circuiting it.
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.transcribe",
        lambda *a, **k: _FakeTranscription(text="do the special thing"),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.execute",
        lambda *a, **k: ExecutionResult(ok=True, message="Opened terminal (kitty)."),
    )
    classifier = _FakeClassifier(
        result=ClassificationResult(
            raw_response='{"intent": "OPEN_TERMINAL"}',
            latency_ms=42.0,
            envelope={
                "schema_version": 1,
                "intent": "OPEN_TERMINAL",
                "confidence": 0.95,
                "args": {},
            },
        )
    )

    result = run_pipeline(**_kwargs(classifier=classifier))

    assert result.ok is True
    assert result.message == "Opened terminal (kitty)."
    assert result.transcript == "do the special thing"
    assert result.intent == "OPEN_TERMINAL"
    assert result.confidence == 0.95
    assert result.llm_latency_ms == 42.0
    assert result.total_ms > 0
    assert classifier.calls == [("system prompt", "do the special thing")]


class _FakeArabicTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return self.text


def test_arabic_routes_to_the_ctc_transcriber_not_whisper(monkeypatch):
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.record_utterance",
        lambda vad, cfg: np.zeros(1600, dtype=np.int16),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.transcribe",
        lambda *a, **k: pytest.fail("whisper must not be used for the Arabic path"),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.execute",
        lambda *a, **k: ExecutionResult(ok=True, message="done"),
    )
    arabic = _FakeArabicTranscriber("اقفل الواتس")
    classifier = _FakeClassifier(
        result=ClassificationResult(
            raw_response="{}",
            latency_ms=1.0,
            envelope={"schema_version": 1, "intent": "CLOSE_APP", "confidence": 0.9, "args": {}},
        )
    )

    result = run_pipeline(**_kwargs(classifier=classifier, language="ar", arabic_transcriber=arabic))

    assert arabic.calls == 1
    assert result.transcript == "اقفل الواتس"


def test_english_still_uses_whisper_even_when_ctc_is_available(monkeypatch):
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.record_utterance",
        lambda vad, cfg: np.zeros(1600, dtype=np.int16),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.transcribe",
        lambda *a, **k: _FakeTranscription(text="open a terminal"),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.execute",
        lambda *a, **k: ExecutionResult(ok=True, message="done"),
    )
    arabic = _FakeArabicTranscriber("should not be used")
    classifier = _FakeClassifier(
        result=ClassificationResult(
            raw_response="{}",
            latency_ms=1.0,
            envelope={"schema_version": 1, "intent": "OPEN_TERMINAL", "confidence": 0.9, "args": {}},
        )
    )

    result = run_pipeline(**_kwargs(classifier=classifier, language="en", arabic_transcriber=arabic))

    assert arabic.calls == 0
    assert result.transcript == "open a terminal"


def test_fastpath_match_skips_the_llm_call_entirely(monkeypatch):
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.record_utterance",
        lambda vad, cfg: np.zeros(1600, dtype=np.int16),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.transcribe",
        lambda *a, **k: _FakeTranscription(text="open a terminal"),
    )
    captured = {}
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.execute",
        lambda envelope, *a, **k: captured.update(envelope=envelope, kwargs=k)
        or ExecutionResult(ok=True, message="Opened terminal (kitty)."),
    )
    classifier = _FakeClassifier(error=AssertionError("the LLM must not be called"))

    result = run_pipeline(**_kwargs(classifier=classifier))

    assert classifier.calls == []
    assert result.ok is True
    assert result.intent == "OPEN_TERMINAL"
    assert result.confidence == 1.0
    assert result.llm_latency_ms == 0.0
    assert captured["envelope"]["intent"] == "OPEN_TERMINAL"
    assert captured["kwargs"]["path"] == "fastpath"


def test_fastpath_miss_falls_through_to_the_llm_unchanged(monkeypatch):
    # A phrase fastpath.py can't confidently resolve (a compound command) must still
    # reach the classifier exactly as before -- fastpath only ever adds a shortcut, it
    # must never remove the existing fallback behavior.
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.record_utterance",
        lambda vad, cfg: np.zeros(1600, dtype=np.int16),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.transcribe",
        lambda *a, **k: _FakeTranscription(text="open obsidian and close the terminal"),
    )
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.execute",
        lambda *a, **k: ExecutionResult(ok=False, message="Sorry, I didn't understand that."),
    )
    classifier = _FakeClassifier(
        result=ClassificationResult(
            raw_response="{}",
            latency_ms=7.0,
            envelope={"schema_version": 1, "intent": "UNRECOGNIZED", "confidence": 0.1, "args": {}},
        )
    )

    result = run_pipeline(**_kwargs(classifier=classifier))

    assert classifier.calls == [("system prompt", "open obsidian and close the terminal")]
    assert result.intent == "UNRECOGNIZED"
    assert result.llm_latency_ms == 7.0
