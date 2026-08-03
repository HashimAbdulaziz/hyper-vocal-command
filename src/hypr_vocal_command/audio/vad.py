"""Silero VAD (ONNX Runtime, no torch) -- single-utterance capture with automatic
end-of-speech detection.

The ONNX inference contract (I/O names, chunk size, context window, LSTM state shape)
is ported from vocalinux's own working implementation
(~/.local/share/vocalinux-install/src/vocalinux/speech_recognition/silero_vad.py),
which already solved this exact problem for this exact model file -- reimplementing it
from a general description would risk subtly wrong chunk/state handling.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import onnxruntime as ort

from . import capture

CHUNK_SIZE = 512  # samples per inference step at 16kHz (32ms) -- fixed by the model
CONTEXT_SIZE = 64  # samples of cross-chunk continuity prepended to each input

_MODEL_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx"
)


def _find_bundled_model() -> Path | None:
    """Reuse vocalinux's already-downloaded copy instead of a redundant download, if present."""
    candidates = Path.home().glob(
        ".local/share/vocalinux/venv/lib/python3.*/site-packages"
        "/vocalinux/speech_recognition/data/silero_vad.onnx"
    )
    return next(candidates, None)


def _cache_path() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data_home) / "hypr-vocal-command" / "models" / "silero_vad.onnx"


def resolve_model_path() -> Path:
    bundled = _find_bundled_model()
    if bundled is not None:
        return bundled

    cached = _cache_path()
    if cached.is_file():
        return cached

    cached.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", _MODEL_URL, timeout=30.0, follow_redirects=True) as response:
        response.raise_for_status()
        with cached.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    return cached


class SileroVAD:
    """Not thread-safe -- speech_probability()/reset() mutate internal LSTM state."""

    def __init__(self, model_path: Path | None = None) -> None:
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(model_path or resolve_model_path()),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._sr = np.array(capture.SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SIZE), dtype=np.float32)

    def speech_probability(self, chunk: np.ndarray) -> float:
        if len(chunk) != CHUNK_SIZE:
            raise ValueError(f"expected {CHUNK_SIZE} samples, got {len(chunk)}")

        audio_f32 = (chunk.astype(np.float32) / 32768.0).reshape(1, -1)
        model_input = np.concatenate([self._context, audio_f32], axis=1)
        self._context = audio_f32[:, -CONTEXT_SIZE:]

        output, self._state = self._session.run(
            None, {"input": model_input, "sr": self._sr, "state": self._state}
        )
        return float(output[0][0])


@dataclass(frozen=True)
class UtteranceConfig:
    threshold: float = 0.55
    # 2.0s (vocalinux's own default, read during Phase 5) is tuned for continuous
    # dictation, where a long trailing pause is genuinely ambiguous (thinking vs. done).
    # Short 1-4 word commands don't need that much confirmation, and this delay is
    # entirely invisible in the CLI's own timing breakdown -- it elapses before
    # "Recorded X.Xs, transcribing..." even prints, so it was silently inflating every
    # invocation's perceived latency by a full extra second beyond what transcribe_ms/
    # llm_latency_ms/total_ms ever showed.
    silence_timeout_s: float = 1.0
    max_duration_s: float = 30.0
    max_initial_silence_s: float = 10.0


def record_utterance(
    vad: SileroVAD, config: UtteranceConfig | None = None
) -> np.ndarray | None:
    """Records from the mic until speech-then-silence is detected.

    Returns the recorded int16 mono PCM buffer, or None if no speech was ever detected
    (pure silence/background noise) within `max_initial_silence_s`.
    """
    config = config or UtteranceConfig()
    vad.reset()
    chunk_duration_s = CHUNK_SIZE / capture.SAMPLE_RATE

    recorded: list[np.ndarray] = []
    has_speech = False
    silence_s = 0.0
    elapsed_s = 0.0

    with capture.open_stream(blocksize=CHUNK_SIZE) as stream:
        for chunk in capture.frames(stream, CHUNK_SIZE):
            recorded.append(chunk)
            elapsed_s += chunk_duration_s

            is_speech = vad.speech_probability(chunk) >= config.threshold

            if is_speech:
                has_speech = True
                silence_s = 0.0
            else:
                silence_s += chunk_duration_s
                if has_speech and silence_s >= config.silence_timeout_s:
                    break
                if not has_speech and elapsed_s >= config.max_initial_silence_s:
                    return None

            if elapsed_s >= config.max_duration_s:
                break

    return np.concatenate(recorded) if has_speech else None
