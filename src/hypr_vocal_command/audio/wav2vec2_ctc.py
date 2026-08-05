"""Egyptian Arabic speech-to-text via a wav2vec2 CTC model, run through ONNX Runtime.

Used for the Arabic path only; English still goes through whisper.cpp. Two independent
reasons this model wins for Egyptian Arabic, both measured on this machine rather than
assumed:

Accuracy. Whisper's `base` model is trained mostly on Modern Standard Arabic, and
Egyptian pronunciation defeats it -- most damagingly on "اقفل" (close), which Egyptians
realize with a glottal stop. In a live A/B on real speech, whisper heard it as "فين"
(where) or produced English gibberish, and the pipeline then *opened* WhatsApp twice
when asked to close it. This model transcribed the same recordings correctly and never
inverted an action: 7/7 correct intents against whisper's 5/7, and 5/7 fully correct
end-to-end against 2/7.

Speed. CTC decodes in a single forward pass, with no autoregressive token-by-token
loop, so it is *faster* than the smaller whisper model despite having more parameters:
~680ms against whisper base's ~1300ms on a 3s utterance. An Egyptian-tuned whisper
`small` was also evaluated and rejected -- same accuracy class, but ~6.1s.

Runtime cost is deliberately zero-new-dependency: the model is exported to ONNX once,
offline, and runs here through the `onnxruntime` session this project already depends
on for voice-activity detection. PyTorch is needed only to produce the .onnx file and
never at runtime. Int8 quantization was tested and rejected: on this CPU (no VNNI) it
was both slower (~1295ms) and less accurate.

The vocabulary is Arabic-script only, which suits the code-switched way these commands
are actually spoken -- an English app name is transcribed phonetically in Arabic
("terminal" -> "تيرمينال"), and the alias map already registers those Arabic forms.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import onnxruntime as ort

_MODEL_FILENAME = "egyptian-wav2vec2.onnx"
_VOCAB_FILENAME = "egyptian-wav2vec2-vocab.json"
_WORD_DELIMITER = "|"


def _models_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg_data_home) / "hypr-vocal-command" / "models"


def model_path() -> Path:
    return _models_dir() / _MODEL_FILENAME


def vocab_path() -> Path:
    return _models_dir() / _VOCAB_FILENAME


def is_available() -> bool:
    """Whether the exported model is present. The Arabic path falls back to whisper when
    it isn't, so a missing model degrades quality rather than breaking the pipeline."""
    return model_path().is_file() and vocab_path().is_file()


@dataclass(frozen=True)
class Wav2Vec2Transcriber:
    session: "ort.InferenceSession"
    id_to_token: dict[int, str]
    pad_id: int

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: mono int16 PCM at 16kHz, as produced by audio.vad.record_utterance()."""
        samples = audio.astype(np.float32) / 32768.0
        # wav2vec2 expects zero-mean/unit-variance input; its feature extractor is
        # configured with do_normalize=True and skipping this yields pure CTC blanks.
        samples = (samples - samples.mean()) / np.sqrt(samples.var() + 1e-7)

        logits = self.session.run(
            None, {"input_values": samples.reshape(1, -1).astype(np.float32)}
        )[0]
        return self._ctc_greedy_decode(logits[0].argmax(axis=-1))

    def _ctc_greedy_decode(self, ids: np.ndarray) -> str:
        # Standard CTC collapse: drop repeats of the same id, then drop blanks.
        pieces: list[str] = []
        previous = -1
        for token_id in ids:
            token_id = int(token_id)
            if token_id != previous and token_id != self.pad_id:
                pieces.append(self.id_to_token.get(token_id, ""))
            previous = token_id
        return "".join(pieces).replace(_WORD_DELIMITER, " ").strip()


def load_transcriber(threads: int = 6) -> Wav2Vec2Transcriber:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.log_severity_level = 3
    session = ort.InferenceSession(
        str(model_path()), sess_options=options, providers=["CPUExecutionProvider"]
    )

    vocab = json.loads(vocab_path().read_text())
    return Wav2Vec2Transcriber(
        session=session,
        id_to_token={index: token for token, index in vocab.items()},
        pad_id=vocab["[PAD]"],
    )
