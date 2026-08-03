import numpy as np

from hypr_vocal_command.audio import vad as vad_module
from hypr_vocal_command.audio.vad import CHUNK_SIZE, UtteranceConfig, record_utterance

CHUNK_DURATION_S = CHUNK_SIZE / 16000


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeVAD:
    """Drives record_utterance's state machine with a scripted probability sequence,
    independent of any real audio/model -- tests our orchestration logic in isolation."""

    def __init__(self, probabilities: list[float]) -> None:
        self._probabilities = iter(probabilities)

    def reset(self) -> None:
        pass

    def speech_probability(self, chunk: np.ndarray) -> float:
        return next(self._probabilities)


def _patch_capture(monkeypatch, probabilities: list[float]) -> None:
    monkeypatch.setattr(vad_module.capture, "open_stream", lambda blocksize: _FakeStream())
    chunks = [np.zeros(CHUNK_SIZE, dtype=np.int16) for _ in probabilities]
    monkeypatch.setattr(vad_module.capture, "frames", lambda stream, blocksize: iter(chunks))


def test_stops_after_silence_timeout_following_speech(monkeypatch):
    # 2 speech chunks, then far more silence than the 2s timeout requires (~63 chunks).
    probabilities = [0.9, 0.9] + [0.0] * 70
    _patch_capture(monkeypatch, probabilities)

    config = UtteranceConfig(silence_timeout_s=2.0, max_duration_s=30.0)
    audio = record_utterance(_FakeVAD(probabilities), config)

    assert audio is not None
    # Should stop once silence_timeout is reached, not consume every available frame.
    assert len(audio) < CHUNK_SIZE * len(probabilities)
    assert len(audio) % CHUNK_SIZE == 0


def test_returns_none_for_pure_silence(monkeypatch):
    # More continuous silence than max_initial_silence_s (10s) requires (~313 chunks).
    probabilities = [0.0] * 320
    _patch_capture(monkeypatch, probabilities)

    config = UtteranceConfig(max_initial_silence_s=10.0)
    audio = record_utterance(_FakeVAD(probabilities), config)

    assert audio is None


def test_stops_at_max_duration_even_without_silence(monkeypatch):
    # Continuous speech the whole time -- silence_timeout never triggers, so
    # max_duration_s must be the thing that stops it.
    probabilities = [0.9] * 2000
    _patch_capture(monkeypatch, probabilities)

    config = UtteranceConfig(max_duration_s=1.0, silence_timeout_s=2.0)
    audio = record_utterance(_FakeVAD(probabilities), config)

    assert audio is not None
    assert len(audio) < CHUNK_SIZE * len(probabilities)


def test_real_silero_model_reports_low_probability_for_silence():
    # Uses the real bundled ONNX model (reused from vocalinux) on a genuine inference
    # call -- validates our I/O contract (chunk/context/state shapes) is actually
    # correct, not just internally consistent with our own mocks above.
    vad = vad_module.SileroVAD()
    silence = np.zeros(CHUNK_SIZE, dtype=np.int16)

    probability = vad.speech_probability(silence)

    assert 0.0 <= probability <= 1.0
    assert probability < 0.3
