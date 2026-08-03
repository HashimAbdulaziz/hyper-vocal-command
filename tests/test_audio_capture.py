from unittest.mock import MagicMock

from hypr_vocal_command.audio import capture


def test_open_stream_uses_expected_parameters(monkeypatch):
    captured = {}

    def fake_input_stream(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(capture.sd, "InputStream", fake_input_stream)

    capture.open_stream(blocksize=512)

    assert captured == {
        "samplerate": 16000,
        "channels": 1,
        "dtype": "int16",
        "blocksize": 512,
    }


def test_frames_yields_mono_channel_from_stream():
    import numpy as np

    stream = MagicMock()
    channel_shaped = np.arange(512).reshape(512, 1).astype(np.int16)
    stream.read.side_effect = [(channel_shaped, False)]

    frame = next(capture.frames(stream, 512))

    assert frame.shape == (512,)
    assert frame.dtype == np.int16
    assert frame[10] == 10
