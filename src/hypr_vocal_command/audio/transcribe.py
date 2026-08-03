"""Whisper.cpp transcription via pywhispercpp.

Defaults to the "base" ggml model (downloaded once, cached under our own XDG data dir)
rather than "tiny". Live A/B testing against real speech (not just synthesized audio)
showed base recovers information tiny drops entirely -- e.g. the digit in "workspace 2"
came through correctly on base while tiny dropped it to "work is based too" -- which is a
genuine model-capacity difference, not something prompt-tuning or gain calibration can
fix. Falls back to vocalinux's already-bundled tiny model if the download isn't possible
(e.g. no network on first run).

Runs in auto-detect language mode so the per-utterance language probability is available
as a telemetry/cross-check signal (used from Phase 8 onward). The final language choice
is restricted to `allowed_languages` (default English/Arabic, the only two pipelines this
project supports) rather than trusting whisper's raw top-1 pick across all 99 languages --
live testing showed garbled short commands frequently "won" as Swedish, Turkish, Polish,
German, or Russian at low-to-moderate confidence, producing useless cross-language
gibberish. We already compute a full per-language probability distribution via
`auto_detect_language()`; restricting the choice to languages we can actually act on
costs nothing and eliminates that entire failure mode.
"""

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
from pywhispercpp.model import Model

_BASE_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
DEFAULT_ALLOWED_LANGUAGES = ("en", "ar")


def _cache_path() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data_home) / "hypr-vocal-command" / "models" / "ggml-base.bin"


def _tiny_fallback_path() -> Path:
    return Path.home() / ".local/share/vocalinux/models/whispercpp/ggml-tiny.bin"


def resolve_model_path() -> Path:
    cached = _cache_path()
    if cached.is_file():
        return cached

    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream(
            "GET", _BASE_MODEL_URL, timeout=60.0, follow_redirects=True
        ) as response:
            response.raise_for_status()
            with cached.open("wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
        return cached
    except httpx.HTTPError:
        tiny = _tiny_fallback_path()
        if tiny.is_file():
            return tiny
        raise FileNotFoundError(
            "Could not download the base ggml model and no local tiny model was found "
            f"(expected vocalinux's bundled copy at {tiny}). Check your network "
            "connection, or pass model_path= explicitly to load_model()."
        ) from None


# Physical core count on this machine (i7-8850H, 6c/12t) -- empirically the fastest
# setting found during Phase 5 benchmarking (12, the hyperthread count, was measurably
# *slower*). That finding was recorded in the plan but never actually wired into the
# default code path until this review caught the gap -- worth defaulting explicitly
# rather than trusting whisper.cpp's own internal heuristic (which may pick 12 here).
_DEFAULT_N_THREADS = 6


def load_model(model_path: Path | None = None, n_threads: int | None = None) -> Model:
    path = model_path or resolve_model_path()
    # NOTE: we previously set temperature_inc=0.0 here to force a single decode pass,
    # suspecting whisper.cpp's temperature-fallback retry loop was the cause of elevated
    # latency. That was wrong and caused a worse regression: temperature fallback is
    # whisper.cpp's own mechanism for detecting and escaping repetition loops (it checks
    # the output's compression ratio; highly-repetitive text triggers a retry at higher
    # temperature). Disabling it removed that safety net -- live testing immediately
    # produced a 50+ times repeated "close this tile." transcript with no fallback left
    # to catch it. Reverted to whisper.cpp's default (temperature_inc left unset). The
    # repetition-loop failure mode is now instead guarded at the application layer, see
    # `_collapse_repeated_sentences()` below -- defense in depth, since fallback reduces
    # but doesn't guarantee eliminating this risk either.
    return Model(str(path), n_threads=n_threads if n_threads is not None else _DEFAULT_N_THREADS)


def _collapse_repeated_sentences(text: str) -> str:
    """Collapse a whisper repetition-loop artifact (the same short sentence echoed
    dozens of times) down to one instance. Cheap, safe defense in depth regardless of
    how often whisper's own temperature-fallback mechanism catches this first."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    collapsed: list[str] = []
    for sentence in sentences:
        if not collapsed or collapsed[-1].lower() != sentence.lower():
            collapsed.append(sentence)
    return " ".join(collapsed)


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str
    language_probability: float
    raw_top_language: str
    raw_top_probability: float


def transcribe(
    model: Model,
    audio: np.ndarray,
    initial_prompt: str | None = None,
    allowed_languages: Sequence[str] = DEFAULT_ALLOWED_LANGUAGES,
    language_hint: str | None = None,
) -> TranscriptionResult:
    """audio: mono int16 PCM at 16kHz, as produced by audio.vad.record_utterance().

    `initial_prompt` biases whisper's decoder toward expected command vocabulary (see
    audio/vocabulary.py). `allowed_languages` restricts the final language choice to
    languages this project actually supports -- `raw_top_language`/`raw_top_probability`
    still expose whisper's unrestricted top pick for telemetry/debugging.

    `language_hint`, when given, skips `auto_detect_language()` entirely and decodes
    directly in that language. Measured during Phase 5: running auto-detect before
    transcribe roughly *doubles* whisper's own encoder cost (~643ms detect + ~759ms
    transcribe vs ~759ms alone, on this hardware). That per-utterance language signal
    only earns its cost once a hotkey-language mismatch check actually consumes it
    (planned for Phase 9's Arabic pipeline) -- until then, paying it on every single-
    language invocation is pure waste. Pass this whenever only one pipeline is reachable.
    """
    audio_f32 = audio.astype(np.float32) / 32768.0

    if language_hint is not None:
        language = language_hint
        probability = 1.0
        raw_top_language = language_hint
        raw_top_probability = 1.0
    else:
        (raw_top_language, raw_top_probability_np), all_probs = model.auto_detect_language(audio_f32)
        raw_top_probability = float(raw_top_probability_np)
        language = max(allowed_languages, key=lambda code: all_probs.get(code, 0.0))
        probability = float(all_probs.get(language, 0.0))

    if initial_prompt:
        segments = model.transcribe(audio_f32, language=language, initial_prompt=initial_prompt)
    else:
        segments = model.transcribe(audio_f32, language=language)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    text = _collapse_repeated_sentences(text)

    return TranscriptionResult(
        text=text,
        language=language,
        language_probability=probability,
        raw_top_language=raw_top_language,
        raw_top_probability=float(raw_top_probability),
    )
