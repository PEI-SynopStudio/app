from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple

import numpy as np
from faster_whisper import WhisperModel

from app.core.config import (
    ERROR_TRANSCRIPTION_FAILED,
    LANGUAGE_SUBTAG_SEPARATOR,
    WHISPER_BEAM_SIZE,
    WHISPER_COMPRESSION_RATIO_THRESHOLD,
    WHISPER_CONDITION_ON_PREVIOUS_TEXT,
    WHISPER_LOG_PROB_THRESHOLD,
    WHISPER_MAX_IDENTICAL_SEGMENTS,
    WHISPER_NO_SPEECH_THRESHOLD,
    WHISPER_VAD_PARAMETERS,
)

_MODEL_ERRORS = (OSError, RuntimeError, ValueError)


@dataclass(frozen=True)
class WhisperWord:
    text: str
    start: float
    end: float
    probability: float


@dataclass(frozen=True)
class WhisperSegment:

    text: str
    start: float
    end: float
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    temperature: Optional[float]
    words: Tuple[WhisperWord, ...]


def whisper_parameters() -> Dict[str, Any]:
    return {
        "beam_size": WHISPER_BEAM_SIZE,
        "vad_filter": True,
        "vad_parameters": dict(WHISPER_VAD_PARAMETERS),
        "word_timestamps": True,
        "condition_on_previous_text": WHISPER_CONDITION_ON_PREVIOUS_TEXT,
        "no_speech_threshold": WHISPER_NO_SPEECH_THRESHOLD,
        "compression_ratio_threshold": WHISPER_COMPRESSION_RATIO_THRESHOLD,
        "log_prob_threshold": WHISPER_LOG_PROB_THRESHOLD,
    }


def transcribe_window(model: WhisperModel, samples: np.ndarray, language: str) -> Iterator[WhisperSegment]:
    try:
        segments, _ = model.transcribe(
            samples, language=language.split(LANGUAGE_SUBTAG_SEPARATOR)[0], **whisper_parameters()
        )
        previous, repeats = None, 0
        for segment in segments:
            words = tuple(
                WhisperWord(word.word.strip(), word.start, word.end, word.probability)
                for word in segment.words or ()
                if word.word.strip()
            )
            if not words:
                continue
            text = segment.text.strip()
            repeats = repeats + 1 if text == previous else 1
            previous = text
            if repeats > WHISPER_MAX_IDENTICAL_SEGMENTS:
                continue
            yield WhisperSegment(
                text, segment.start, segment.end, segment.avg_logprob, segment.no_speech_prob,
                segment.compression_ratio, segment.temperature, words,
            )
    except _MODEL_ERRORS as exc:
        raise RuntimeError(ERROR_TRANSCRIPTION_FAILED.format(details=exc)) from exc
