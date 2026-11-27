from typing import Literal


from types import SimpleNamespace

import numpy as np
import pytest
from huggingface_hub import snapshot_download

from app.core.config import ALIGNMENT_MODEL_FILES, ALIGNMENT_MODELS, get_settings
from app.services.speech import alignment
from app.services.speech.alignment import align_segment, align_words, ctc_viterbi
from app.services.speech.models import load_aligner
from app.services.speech.transcription import WhisperSegment, WhisperWord

BLANK, DELIMITER = 0, 4
VOCAB = {"o": 1, "l": 2, "á": 3}


def emissions(frame_tokens, vocab_size=5, floor=1e-4):
    log_probs = np.full((len(frame_tokens), vocab_size), np.log(floor))
    for frame, token in enumerate(frame_tokens):
        log_probs[frame, token] = np.log(1 - floor * (vocab_size - 1))
    return log_probs


def word(text, start, end, probability=0.9):
    return WhisperWord(text, start, end, probability)


def segment(words, start=2.0, end=3.0):
    return WhisperSegment(" ".join(w.text for w in words), start, end, -0.2, 0.01, 1.1, 0.0, tuple(words))


def _aligner_cached() -> bool:
    try:
        snapshot_download(
            ALIGNMENT_MODELS["pt"],
            cache_dir=str(get_settings().speech_models_dir),
            allow_patterns=list[Literal['*.json', '*.safetensors', 'pytorch_model.bin']](ALIGNMENT_MODEL_FILES),
            local_files_only=True,
        )
    except (OSError, ValueError):
        return False
    return True


def test_viterbi_finds_the_frames_of_each_token():
    assert ctc_viterbi(emissions([0, 0, 1, 1, 0, 2, 2, 2, 0]), [1, 2], BLANK) == [(2, 4), (5, 8)]


def test_viterbi_separates_a_repeated_token_with_a_blank():
    assert ctc_viterbi(emissions([1, 1, 0, 1, 0]), [1, 1], BLANK) == [(0, 2), (3, 4)]


def test_viterbi_gives_up_when_the_tokens_do_not_fit():
    assert ctc_viterbi(emissions([1]), [1, 1], BLANK) is None


def test_words_are_aligned_and_a_number_keeps_its_whisper_times():
    log_probs = emissions([0, 1, 2, 3, 3, 0, DELIMITER, 2, 3, 0])
    words = [word("Olá,", 1.0, 1.3), word("2024", 1.3, 1.5, 0.8), word("lá", 1.5, 1.8)]

    result = align_words(log_probs, 0.2, 1.0, words, VOCAB, BLANK, DELIMITER)

    assert [(w.text, round(w.start, 3), round(w.end, 3), w.aligned) for w in result] == [
        ("Olá,", 1.02, 1.1, True),
        ("2024", 1.3, 1.5, False),
        ("lá", 1.14, 1.18, True),
    ]
    assert result[1].probability == 0.8


def test_too_short_audio_keeps_every_whisper_time():
    result = align_words(emissions([1]), 0.02, 0.0, [word("olá", 0.0, 0.5)], VOCAB, BLANK, DELIMITER)

    assert [(w.start, w.end, w.aligned) for w in result] == [(0.0, 0.5, False)]


def test_segment_is_aligned_inside_its_padded_interval(monkeypatch):
    received = []

    def fake_emissions(aligner, samples):
        received.append(len(samples))
        return emissions([0] * 40 + [1, 2, 3] + [0] * 57)

    tokenizer = SimpleNamespace(
        word_delimiter_token="|",
        pad_token_id=BLANK,
        get_vocab=lambda: {"<pad>": BLANK, **VOCAB, "|": DELIMITER},
        convert_tokens_to_ids=lambda token: DELIMITER,
    )
    monkeypatch.setattr(alignment, "_emissions", fake_emissions)
    aligner = SimpleNamespace(processor=SimpleNamespace(tokenizer=tokenizer))

    [aligned] = align_segment(aligner, np.zeros(10 * 16000, dtype=np.float32), segment([word("olá", 2.0, 3.0)]))

    assert received == [2 * 16000]
    assert (round(aligned.start, 3), round(aligned.end, 3), aligned.aligned) == (2.3, 2.36, True)


@pytest.mark.skipif(not _aligner_cached(), reason="the wav2vec2 weights are not in SPEECH_MODELS_DIR")
def test_real_model_keeps_the_word_inside_its_padded_interval():
    [aligned] = align_segment(load_aligner("pt"), np.zeros(5 * 16000, dtype=np.float32), segment([word("olá", 1.0, 2.0)], 1.0, 2.0))

    assert 0.5 <= aligned.start <= aligned.end <= 2.5
