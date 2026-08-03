"""Audio level measurement -- lets a user calibrate microphone input gain empirically
(peak level, clipping) instead of guessing at volume percentages."""

from dataclasses import dataclass

import numpy as np

_INT16_MAX = 32767


@dataclass(frozen=True)
class LevelReport:
    peak_pct: float
    rms_pct: float
    clipped_samples: int
    total_samples: int

    @property
    def clipped(self) -> bool:
        return self.clipped_samples > 0


def measure_levels(audio: np.ndarray) -> LevelReport:
    if audio.size == 0:
        return LevelReport(peak_pct=0.0, rms_pct=0.0, clipped_samples=0, total_samples=0)

    abs_audio = np.abs(audio.astype(np.int64))
    peak = int(abs_audio.max())
    rms = float(np.sqrt(np.mean(abs_audio.astype(np.float64) ** 2)))
    clipped = int(np.sum(abs_audio >= _INT16_MAX))

    return LevelReport(
        peak_pct=peak / _INT16_MAX * 100,
        rms_pct=rms / _INT16_MAX * 100,
        clipped_samples=clipped,
        total_samples=int(audio.size),
    )
