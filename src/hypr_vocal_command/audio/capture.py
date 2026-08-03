"""Microphone capture via sounddevice, 16kHz mono int16 -- the format Silero VAD and
whisper.cpp both expect.
"""

from collections.abc import Iterator

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1


def open_stream(blocksize: int) -> sd.InputStream:
    return sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16", blocksize=blocksize
    )


def frames(stream: sd.InputStream, blocksize: int) -> Iterator[np.ndarray]:
    """Yields consecutive mono int16 frames of exactly `blocksize` samples from an
    already-started stream."""
    while True:
        data, _overflowed = stream.read(blocksize)
        yield data[:, 0]
