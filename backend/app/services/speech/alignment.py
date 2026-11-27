import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch

from app.core.config import (
    ALIGNMENT_PAD_SECONDS,
    AUDIO_SAMPLE_RATE,
    ERROR_ALIGNMENT_FAILED,
    VIDEO_START_SECONDS,
)
from app.services.speech.models import LoadedAligner
from app.services.speech.transcription import WhisperSegment, WhisperWord

_NORMAL_FORM = "NFC"


@dataclass(frozen=True)
class AlignedWord:

    text: str
    start: float
    end: float
    probability: float
    aligned: bool


def align_segment(aligner: LoadedAligner, samples: np.ndarray, segment: WhisperSegment) -> Tuple[AlignedWord, ...]:
    start = max(VIDEO_START_SECONDS, segment.start - ALIGNMENT_PAD_SECONDS)
    end = min(len(samples) / AUDIO_SAMPLE_RATE, segment.end + ALIGNMENT_PAD_SECONDS)
    piece = samples[round(start * AUDIO_SAMPLE_RATE):round(end * AUDIO_SAMPLE_RATE)]
    tokenizer = aligner.processor.tokenizer
    delimiter = tokenizer.word_delimiter_token
    vocab = {token: index for token, index in tokenizer.get_vocab().items() if len(token) == 1 and token != delimiter}
    return align_words(
        _emissions(aligner, piece),
        len(piece) / AUDIO_SAMPLE_RATE,
        start,
        segment.words,
        vocab,
        tokenizer.pad_token_id,
        tokenizer.convert_tokens_to_ids(delimiter),
    )


def align_words(
    log_probs: np.ndarray,
    duration_seconds: float,
    start_seconds: float,
    words: Sequence[WhisperWord],
    vocab: Dict[str, int],
    blank: int,
    delimiter: int,
) -> Tuple[AlignedWord, ...]:
    tokens: List[int] = []
    ranges: List[Optional[Tuple[int, int]]] = []
    for word in words:
        ids = _word_tokens(word.text, vocab)
        if not ids:
            ranges.append(None)
            continue
        if tokens:
            tokens.append(delimiter)
        ranges.append((len(tokens), len(tokens) + len(ids)))
        tokens.extend(ids)

    spans = ctc_viterbi(log_probs, tokens, blank) if tokens and len(log_probs) else None
    aligned = []
    for word, token_range in zip(words, ranges):
        if spans is None or token_range is None:
            aligned.append(AlignedWord(word.text, word.start, word.end, word.probability, False))
            continue
        frame_seconds = duration_seconds / len(log_probs)
        first, last = spans[token_range[0]][0], spans[token_range[1] - 1][1]
        aligned.append(
            AlignedWord(
                word.text,
                start_seconds + first * frame_seconds,
                start_seconds + last * frame_seconds,
                word.probability,
                True,
            )
        )
    return tuple(aligned)


def ctc_viterbi(log_probs: np.ndarray, tokens: Sequence[int], blank: int) -> Optional[List[Tuple[int, int]]]:
    frames = len(log_probs)
    if frames < len(tokens):
        return None
    states = np.full(2 * len(tokens) + 1, blank)
    states[1::2] = tokens
    size = len(states)
    can_skip = np.zeros(size, dtype=bool)
    can_skip[2:] = (states[2:] != blank) & (states[2:] != states[:-2])

    score = np.full(size, -np.inf)
    score[:2] = log_probs[0, states[:2]]
    back = np.zeros((frames, size), dtype=np.int8)
    columns = np.arange(size)
    for frame in range(1, frames):
        from_previous = np.concatenate(([-np.inf], score[:-1]))
        from_skip = np.where(can_skip, np.concatenate(([-np.inf, -np.inf], score[:-2])), -np.inf)
        choices = np.stack((score, from_previous, from_skip))
        back[frame] = np.argmax(choices, axis=0)
        score = choices[back[frame], columns] + log_probs[frame, states]

    state = size - 1 if score[-1] >= score[-2] else size - 2
    if not np.isfinite(score[state]):
        return None
    path = np.empty(frames, dtype=int)
    for frame in range(frames - 1, -1, -1):
        path[frame] = state
        state -= int(back[frame, state])
    return [
        (int(hits[0]), int(hits[-1]) + 1)
        for hits in (np.flatnonzero(path == 2 * index + 1) for index in range(len(tokens)))
    ]


def _word_tokens(text: str, vocab: Dict[str, int]) -> List[int]:
    return [vocab[char] for char in unicodedata.normalize(_NORMAL_FORM, text.lower()) if char in vocab]


def _emissions(aligner: LoadedAligner, samples: np.ndarray) -> np.ndarray:
    try:
        inputs = aligner.processor(samples, sampling_rate=AUDIO_SAMPLE_RATE, return_tensors="pt").input_values
        with torch.inference_mode():
            logits = aligner.model(inputs.to(aligner.model.device)).logits[0]
        return torch.log_softmax(logits, dim=-1).cpu().numpy()
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError(ERROR_ALIGNMENT_FAILED.format(details=exc)) from exc
