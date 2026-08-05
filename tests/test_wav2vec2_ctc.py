import numpy as np

from hypr_vocal_command.audio import wav2vec2_ctc
from hypr_vocal_command.audio.wav2vec2_ctc import Wav2Vec2Transcriber

# Minimal stand-in vocabulary: "|" is the word delimiter, 3 is the CTC blank.
_VOCAB = {"|": 0, "ا": 1, "ب": 2, "[PAD]": 3}
_ID_TO_TOKEN = {index: token for token, index in _VOCAB.items()}


class _FakeSession:
    def __init__(self, logits: np.ndarray) -> None:
        self._logits = logits
        self.received: dict = {}

    def run(self, _outputs, inputs):
        self.received = inputs
        return [self._logits]


def _transcriber_returning(predicted_ids: list[int]) -> tuple[Wav2Vec2Transcriber, _FakeSession]:
    # One-hot logits so argmax reproduces exactly the ids we want to decode.
    logits = np.full((1, len(predicted_ids), len(_VOCAB)), -10.0, dtype=np.float32)
    for frame, token_id in enumerate(predicted_ids):
        logits[0, frame, token_id] = 10.0
    session = _FakeSession(logits)
    return (
        Wav2Vec2Transcriber(session=session, id_to_token=_ID_TO_TOKEN, pad_id=_VOCAB["[PAD]"]),
        session,
    )


def test_ctc_decode_collapses_repeats_and_drops_blanks():
    # ا ا <blank> ا ب  ->  "اا" is collapsed to "ا", the blank separates the next "ا"
    transcriber, _ = _transcriber_returning([1, 1, 3, 1, 2])
    assert transcriber.transcribe(np.zeros(1600, dtype=np.int16)) == "ااب"


def test_ctc_decode_maps_word_delimiter_to_space():
    transcriber, _ = _transcriber_returning([1, 0, 2])
    assert transcriber.transcribe(np.zeros(1600, dtype=np.int16)) == "ا ب"


def test_all_blank_output_decodes_to_empty_string():
    # This is what an out-of-distribution recording produces; it must be an empty
    # transcript (which the pipeline already handles) rather than garbage.
    transcriber, _ = _transcriber_returning([3, 3, 3])
    assert transcriber.transcribe(np.zeros(1600, dtype=np.int16)) == ""


def test_audio_is_normalized_to_zero_mean_unit_variance():
    # wav2vec2's feature extractor uses do_normalize=True; skipping this yields pure
    # CTC blanks, so the normalization is load-bearing rather than cosmetic.
    transcriber, session = _transcriber_returning([1])
    audio = (np.random.default_rng(0).normal(0.3, 0.2, 16000) * 10000).astype(np.int16)

    transcriber.transcribe(audio)

    values = session.received["input_values"]
    assert values.shape[0] == 1
    assert abs(float(values.mean())) < 1e-4
    assert abs(float(values.std()) - 1.0) < 1e-3


def test_is_available_is_false_when_model_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(wav2vec2_ctc, "_models_dir", lambda: tmp_path)
    assert wav2vec2_ctc.is_available() is False


def test_is_available_is_true_when_both_files_present(monkeypatch, tmp_path):
    monkeypatch.setattr(wav2vec2_ctc, "_models_dir", lambda: tmp_path)
    (tmp_path / "egyptian-wav2vec2.onnx").write_bytes(b"x")
    (tmp_path / "egyptian-wav2vec2-vocab.json").write_text("{}")
    assert wav2vec2_ctc.is_available() is True
