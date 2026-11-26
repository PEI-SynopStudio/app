import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from app.core.config import (
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    ERROR_FILE_NOT_FOUND,
    ERROR_UNEXPECTED_WAV_FORMAT,
    PCM_FULL_SCALE,
    PCM_NUMPY_DTYPE,
    PCM_SAMPLE_WIDTH_BYTES,
    TRANSCRIPTION_CUT_FRAME_SECONDS,
    TRANSCRIPTION_CUT_PAUSE_SECONDS,
    TRANSCRIPTION_CUT_SEARCH_SECONDS,
    TRANSCRIPTION_WINDOW_SECONDS,
    WAV_READ_MODE,
)


@dataclass(frozen=True)
class AudioWindow:

    start_seconds: float
    samples: np.ndarray


def iter_audio_windows(
    wav_path: Path,
    window_seconds: float = TRANSCRIPTION_WINDOW_SECONDS,
    search_seconds: float = TRANSCRIPTION_CUT_SEARCH_SECONDS,
) -> Iterator[AudioWindow]:
    if not wav_path.exists():
        raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=wav_path))

    with wave.open(str(wav_path), WAV_READ_MODE) as wav:
        _check_format(wav, wav_path)
        window_frames = round(window_seconds * AUDIO_SAMPLE_RATE)
        search_frames = round(search_seconds * AUDIO_SAMPLE_RATE)
        buffer = np.empty(0, dtype=np.float32)
        position = 0
        while True:
            missing = window_frames - len(buffer)
            chunk = np.frombuffer(wav.readframes(missing), dtype=PCM_NUMPY_DTYPE).astype(np.float32) / PCM_FULL_SCALE
            buffer = np.concatenate((buffer, chunk))
            if len(chunk) < missing:
                if len(buffer):
                    yield AudioWindow(position / AUDIO_SAMPLE_RATE, buffer)
                return
            cut = _quietest_cut(buffer, search_frames)
            yield AudioWindow(position / AUDIO_SAMPLE_RATE, buffer[:cut])
            position += cut
            buffer = buffer[cut:]


def audio_duration_seconds(wav_path: Path) -> float:
    if not wav_path.exists():
        raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=wav_path))
    with wave.open(str(wav_path), WAV_READ_MODE) as wav:
        _check_format(wav, wav_path)
        return wav.getnframes() / AUDIO_SAMPLE_RATE


def _check_format(wav: wave.Wave_read, wav_path: Path) -> None:
    actual = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth())
    if actual != (AUDIO_SAMPLE_RATE, AUDIO_CHANNELS, PCM_SAMPLE_WIDTH_BYTES):
        raise ValueError(
            ERROR_UNEXPECTED_WAV_FORMAT.format(
                rate=AUDIO_SAMPLE_RATE, actual_rate=actual[0], channels=actual[1], width=actual[2], path=wav_path
            )
        )


def _quietest_cut(buffer: np.ndarray, search_frames: int) -> int:
    frame_frames = round(TRANSCRIPTION_CUT_FRAME_SECONDS * AUDIO_SAMPLE_RATE)
    pause_frames = round(TRANSCRIPTION_CUT_PAUSE_SECONDS / TRANSCRIPTION_CUT_FRAME_SECONDS)
    region_start = len(buffer) - search_frames
    frames = search_frames // frame_frames
    region = buffer[region_start:region_start + frames * frame_frames]
    energy = np.square(region).reshape(frames, frame_frames).mean(axis=1)
    pause = np.convolve(energy, np.ones(pause_frames), mode="valid")
    return region_start + (int(np.argmin(pause)) + pause_frames // 2) * frame_frames
