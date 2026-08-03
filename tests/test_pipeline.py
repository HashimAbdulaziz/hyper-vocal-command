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
    monkeypatch.setattr(
        "hypr_vocal_command.pipeline.transcribe",
        lambda *a, **k: _FakeTranscription(text="open a terminal"),
    )
    classifier = _FakeClassifier(error=httpx.ConnectError("connection refused"))

    result = run_pipeline(**_kwargs(classifier=classifier))

    assert result.ok is False
    assert "LLM request failed" in result.message
    assert result.transcript == "open a terminal"


def test_full_success_path_executes_and_reports_all_fields(monkeypatch):
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
    assert result.transcript == "open a terminal"
    assert result.intent == "OPEN_TERMINAL"
    assert result.confidence == 0.95
    assert result.llm_latency_ms == 42.0
    assert result.total_ms > 0
    assert classifier.calls == [("system prompt", "open a terminal")]
