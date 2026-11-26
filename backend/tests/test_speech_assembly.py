import pytest

from app.core.config import JobErrorCodeEnum
from app.core.exceptions import MediaRejectedError
from app.services.speech.alignment import AlignedWord
from app.services.speech.assembly import build_document, build_segment
from app.services.speech.transcription import WhisperSegment, WhisperWord


def whisper_segment(text="Bom dia.", start=0.5, end=2.5):
    return WhisperSegment(text, start, end, -0.25, 0.02, 1.3, 0.2, (WhisperWord(text, start, end, 0.9),))


def aligned(text, start, end, probability=0.9, is_aligned=True):
    return AlignedWord(text, start, end, probability, is_aligned)


def test_times_are_moved_to_the_original_recording_and_rounded():
    segment = build_segment(whisper_segment(), [aligned("Bom", 1.0201, 1.3), aligned("dia.", 1.35, 1.8)], 600.0)

    assert [(word.start, word.end) for word in segment.words] == [(601.02, 601.3), (601.35, 601.8)]


def test_segment_spans_its_words_instead_of_the_whisper_interval():
    words = [aligned("Bom", 1.0, 1.3), aligned("2024", 0.9, 2.0, is_aligned=False), aligned("dia.", 1.35, 1.8)]

    segment = build_segment(whisper_segment(start=0.5, end=2.5), words, 10.0)

    assert (segment.start, segment.end) == (10.9, 12.0)


def test_segment_keeps_the_text_and_whisper_scores_and_averages_word_confidence():
    words = [aligned("Bom", 1.0, 1.3, 0.8), aligned("dia.", 1.35, 1.8, 0.6, is_aligned=False)]

    segment = build_segment(whisper_segment("Bom  dia."), words, 0.0)

    assert segment.text == "Bom  dia."
    assert (segment.avg_logprob, segment.no_speech_prob, segment.compression_ratio, segment.temperature) == (-0.25, 0.02, 1.3, 0.2)
    assert segment.confidence == pytest.approx(0.7)
    assert [word.aligned for word in segment.words] == [True, False]


def test_document_holds_the_segments_in_order():
    first = build_segment(whisper_segment("Bom dia."), [aligned("Bom", 0.0, 0.3), aligned("dia.", 0.35, 0.8)], 0.0)
    second = build_segment(whisper_segment("Olá."), [aligned("Olá.", 1.0, 1.4)], 0.0)

    document = build_document("pt-PT", [first, second])

    assert document.language == "pt-PT"
    assert document.ai_generated is True
    assert [segment.text for segment in document.segments] == ["Bom dia.", "Olá."]


def test_no_segments_means_no_speech_detected():
    with pytest.raises(MediaRejectedError) as raised:
        build_document("pt", [])

    assert raised.value.code == JobErrorCodeEnum.NO_SPEECH_DETECTED
    assert isinstance(raised.value, ValueError)
