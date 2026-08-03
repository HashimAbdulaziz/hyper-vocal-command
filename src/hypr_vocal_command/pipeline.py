"""The core record -> transcribe -> classify -> execute voice-command pipeline.

Shared by the CLI's `run-once` (cold: builds one-shot resources, runs once, exits) and
`daemon.py`'s per-connection handler (warm: resources are built once at daemon startup
and reused across every connection) -- the exact same logic either way, just a
difference in resource lifetime around it.
"""

import time
from dataclasses import dataclass

import httpx
from pywhispercpp.model import Model

from .audio.transcribe import transcribe
from .audio.vad import SileroVAD, UtteranceConfig, record_utterance
from .config import Config
from .executor import execute
from .llm.cache import CachedClassifier
from .utils.notifier import notify


@dataclass(frozen=True)
class PipelineResult:
    ok: bool
    message: str
    transcript: str
    intent: str | None
    confidence: float | None
    transcribe_ms: float
    llm_latency_ms: float
    total_ms: float


def run_pipeline(
    *,
    vad: SileroVAD,
    whisper_model: Model,
    classifier: CachedClassifier,
    system_prompt: str,
    vocabulary_prompt: str,
    config: Config,
    language: str = "en",
) -> PipelineResult:
    pipeline_start = time.monotonic()

    audio = record_utterance(vad, UtteranceConfig())
    if audio is None:
        return PipelineResult(
            ok=False,
            message="No speech detected.",
            transcript="",
            intent=None,
            confidence=None,
            transcribe_ms=0.0,
            llm_latency_ms=0.0,
            total_ms=(time.monotonic() - pipeline_start) * 1000,
        )

    transcribe_start = time.monotonic()
    transcription = transcribe(
        whisper_model,
        audio,
        initial_prompt=vocabulary_prompt,
        allowed_languages=config.allowed_transcription_languages,
        language_hint=language,
    )
    transcribe_ms = (time.monotonic() - transcribe_start) * 1000

    if not transcription.text:
        return PipelineResult(
            ok=False,
            message="Empty transcript, nothing to classify.",
            transcript="",
            intent=None,
            confidence=None,
            transcribe_ms=transcribe_ms,
            llm_latency_ms=0.0,
            total_ms=(time.monotonic() - pipeline_start) * 1000,
        )

    try:
        result = classifier.classify(system_prompt, transcription.text)
    except httpx.HTTPError as exc:
        return PipelineResult(
            ok=False,
            message=f"LLM request failed: {exc}",
            transcript=transcription.text,
            intent=None,
            confidence=None,
            transcribe_ms=transcribe_ms,
            llm_latency_ms=0.0,
            total_ms=(time.monotonic() - pipeline_start) * 1000,
        )

    recognized_intent = result.envelope.get("intent", "?")
    recognized_confidence = result.envelope.get("confidence", 0.0)
    notify(
        "hypr-vocal-command",
        f"Heard: {transcription.text!r} -> {recognized_intent} ({recognized_confidence:.0%})",
    )

    exec_result = execute(
        result.envelope,
        config,
        raw_llm_response=result.raw_response,
        llm_latency_ms=result.latency_ms,
        transcript=transcription.text,
    )
    total_ms = (time.monotonic() - pipeline_start) * 1000
    return PipelineResult(
        ok=exec_result.ok,
        message=exec_result.message,
        transcript=transcription.text,
        intent=recognized_intent,
        confidence=recognized_confidence,
        transcribe_ms=transcribe_ms,
        llm_latency_ms=result.latency_ms,
        total_ms=total_ms,
    )
