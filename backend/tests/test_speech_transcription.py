from dataclasses import dataclass

import numpy as np
import pytest
from faster_whisper import download_model

from app.core.config import WHISPER_BEAM_SIZE, get_settings
from app.services.speech.models import load_whisper
from app.services.speech.transcription import transcribe_window, whisper_parameters


@dataclass
class FakeWord:
    word: str
    start: float
    end: float
    probability: float = 0.9


@dataclass
class FakeSegment:
    text: str
    start: float
    end: float
    words: list
    avg_logprob: float = -0.2
    no_speech_prob: float = 0.01
    compression_ratio: float = 1.2
    temperature: float = 0.0


class FakeWhisper:
    """Stands in for WhisperModel: returns the given segments lazily, or fails while they are read."""

    def __init__(self, segments=(), error=None):
        self.segments, self.error, self.calls = segments, error, []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)

        def generate():
            if self.error:
                raise self.error
            yield from self.segments

        return generate(), None


def spoken(text, start, end):
    return FakeSegment(text, start, end, [FakeWord(text, start, end)])


def _whisper_cached() -> bool:
    settings = get_settings()
    try:
        download_model(settings.whisper_model, cache_dir=str(settings.speech_models_dir), local_files_only=True)
    except (OSError, ValueError):
        return False
    return True


def test_segment_keeps_its_times_scores_and_words():
    model = FakeWhisper([FakeSegment(" Olá, mundo!", 1.0, 2.0, [FakeWord(" Olá,", 1.0, 1.4, 0.8), FakeWord(" mundo!", 1.5, 2.0)])])

    [segment] = transcribe_window(model, np.zeros(16000, dtype=np.float32), "pt")

    assert (segment.text, segment.start, segment.end, segment.avg_logprob) == ("Olá, mundo!", 1.0, 2.0, -0.2)
    assert [(word.text, word.start, word.probability) for word in segment.words] == [("Olá,", 1.0, 0.8), ("mundo!", 1.5, 0.9)]


def test_faster_whisper_gets_vad_word_times_and_the_primary_language():
    model = FakeWhisper()

    list(transcribe_window(model, np.zeros(16000, dtype=np.float32), "pt-PT"))

    [call] = model.calls
    assert call["language"] == "pt"
    assert call["vad_filter"] is True and call["word_timestamps"] is True
    assert call["beam_size"] == WHISPER_BEAM_SIZE
    assert {key: call[key] for key in whisper_parameters()} == whisper_parameters()


def test_text_is_never_rewritten():
    model = FakeWhisper([spoken("  Isto é, tipo, ehh... O FMI!! ", 0.0, 3.0)])

    [segment] = transcribe_window(model, np.zeros(16000, dtype=np.float32), "pt")

    assert segment.text == "Isto é, tipo, ehh... O FMI!!"


def test_segment_without_words_is_dropped():
    model = FakeWhisper([FakeSegment(" ", 0.0, 1.0, []), FakeSegment(" ", 1.0, 2.0, None), spoken(" Bom dia.", 2.0, 3.0)])

    assert [segment.text for segment in transcribe_window(model, np.zeros(16000, dtype=np.float32), "pt")] == ["Bom dia."]


def test_a_loop_of_identical_segments_is_cut():
    loop = [spoken(" Obrigado.", second, second + 1) for second in range(5)] + [spoken(" Fim.", 5, 6)]

    texts = [segment.text for segment in transcribe_window(FakeWhisper(loop), np.zeros(16000, dtype=np.float32), "pt")]

    assert texts == ["Obrigado.", "Obrigado.", "Fim."]


def test_library_error_becomes_runtime_error():
    model = FakeWhisper(error=RuntimeError("CTranslate2 failed"))

    with pytest.raises(RuntimeError, match="could not transcribe the audio: CTranslate2 failed"):
        list(transcribe_window(model, np.zeros(16000, dtype=np.float32), "pt"))


@pytest.mark.skipif(not _whisper_cached(), reason="the faster-whisper weights are not in SPEECH_MODELS_DIR")
def test_silence_produces_no_segments():
    assert list(transcribe_window(load_whisper().model, np.zeros(3 * 16000, dtype=np.float32), "pt")) == []
