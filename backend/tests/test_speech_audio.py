import wave

import numpy as np
import pytest

from app.services.speech.audio import iter_audio_windows

RATE = 16000


def write_wav(path, parts, rate=RATE, channels=1):
    tones = [amplitude * np.sin(2 * np.pi * 440 * np.arange(int(seconds * rate)) / rate) for seconds, amplitude in parts]
    pcm = (np.concatenate(tones) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(np.repeat(pcm, channels).tobytes())
    return pcm.astype(np.float32) / 32768


def test_missing_wav_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(iter_audio_windows(tmp_path / "missing.wav"))


@pytest.mark.parametrize("rate, channels", [(48000, 1), (16000, 2)])
def test_wav_that_was_not_normalized_is_rejected(tmp_path, rate, channels):
    path = tmp_path / "audio.wav"
    write_wav(path, [(1, 0.5)], rate=rate, channels=channels)

    with pytest.raises(ValueError, match="Expected a 16000 Hz mono"):
        list(iter_audio_windows(path))


def test_short_audio_is_a_single_window(tmp_path):
    path = tmp_path / "audio.wav"
    original = write_wav(path, [(3, 0.5)])

    windows = list(iter_audio_windows(path, window_seconds=10, search_seconds=2))

    assert len(windows) == 1
    assert windows[0].start_seconds == 0.0
    assert np.array_equal(windows[0].samples, original)


def test_windows_hold_every_sample_once(tmp_path):
    path = tmp_path / "audio.wav"
    original = write_wav(path, [(25, 0.5)])

    windows = list(iter_audio_windows(path, window_seconds=10, search_seconds=2))

    assert np.array_equal(np.concatenate([window.samples for window in windows]), original)
    for previous, current in zip(windows, windows[1:]):
        assert current.start_seconds == pytest.approx(previous.start_seconds + len(previous.samples) / RATE)


def test_window_ends_inside_a_pause(tmp_path):
    path = tmp_path / "audio.wav"
    write_wav(path, [(9, 0.5), (0.5, 0), (5.5, 0.5)])

    first = next(iter_audio_windows(path, window_seconds=10, search_seconds=2))

    assert 9.0 < len(first.samples) / RATE < 9.5


def test_a_short_gap_inside_a_word_is_not_taken_for_a_pause(tmp_path):
    path = tmp_path / "audio.wav"
    write_wav(path, [(8.5, 0.5), (0.05, 0), (0.45, 0.5), (0.3, 0), (5.7, 0.5)])

    first = next(iter_audio_windows(path, window_seconds=10, search_seconds=2))

    assert 9.0 < len(first.samples) / RATE < 9.3


def test_samples_are_float32_between_minus_one_and_one(tmp_path):
    path = tmp_path / "audio.wav"
    write_wav(path, [(1, 1.0)])

    samples = next(iter_audio_windows(path)).samples

    assert samples.dtype == np.float32
    assert samples.min() >= -1.0 and samples.max() <= 1.0
