import numpy as np

from hypr_vocal_command.audio.levels import measure_levels


def test_silence_reports_zero_levels():
    report = measure_levels(np.zeros(1600, dtype=np.int16))
    assert report.peak_pct == 0.0
    assert report.rms_pct == 0.0
    assert report.clipped_samples == 0
    assert report.clipped is False


def test_empty_array_does_not_raise():
    report = measure_levels(np.array([], dtype=np.int16))
    assert report.peak_pct == 0.0
    assert report.total_samples == 0


def test_known_amplitude_reports_expected_peak_percentage():
    # Half of int16 max -> ~50% peak.
    audio = np.array([16384, -16384, 0, 100], dtype=np.int16)
    report = measure_levels(audio)
    assert 49.0 < report.peak_pct < 51.0


def test_clipping_is_detected():
    audio = np.array([32767, -32767, 100, -100], dtype=np.int16)
    report = measure_levels(audio)
    assert report.clipped is True
    assert report.clipped_samples == 2


def test_rms_is_lower_than_peak_for_varying_signal():
    rng = np.random.default_rng(42)
    audio = (rng.standard_normal(16000) * 5000).astype(np.int16)
    report = measure_levels(audio)
    assert report.rms_pct < report.peak_pct
