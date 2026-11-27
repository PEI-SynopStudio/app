from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.job import JobCreateSchema, JobRequestMessage, TranscriptionParams
from app.schemas.transcript import TranscriptDocument, TranscriptionOutput, TranscriptSegment, TranscriptWord


def word(text="olá", start=1.0, end=1.4, confidence=0.9, aligned=True):
    return TranscriptWord(text=text, start=start, end=end, confidence=confidence, aligned=aligned)


def segment(words=None):
    return TranscriptSegment(
        text="olá", start=1.0, end=1.4, confidence=0.9, avg_logprob=-0.2, no_speech_prob=0.01,
        compression_ratio=1.1, temperature=0.0, words=[word()] if words is None else words,
    )


def test_requestmessage_carries_speech_fields():
    msg = JobRequestMessage(
        job_id=uuid4(),
        project_id=uuid4(),
        parameters=TranscriptionParams(media_id=uuid4()),
        audio_key="audio/audio.wav",
        time_offset_seconds=12.5,
    )

    restored = JobRequestMessage.model_validate_json(msg.model_dump_json())
    assert (restored.audio_key, restored.time_offset_seconds) == ("audio/audio.wav", 12.5)


def test_requestmessage_starts_at_the_beginning_by_default():
    msg = JobRequestMessage(job_id=uuid4(), project_id=uuid4(), parameters=TranscriptionParams(media_id=uuid4()))

    assert (msg.audio_key, msg.time_offset_seconds) == (None, 0.0)


def test_negative_time_offset_is_rejected():
    with pytest.raises(ValidationError):
        JobRequestMessage(
            job_id=uuid4(), project_id=uuid4(), parameters=TranscriptionParams(media_id=uuid4()), time_offset_seconds=-1
        )


def test_client_cannot_send_internal_speech_fields():
    with pytest.raises(ValidationError):
        JobCreateSchema.model_validate(
            {"parameters": {"job_type": "transcription", "media_id": str(uuid4()), "audio_key": "../x.wav"}}
        )


def test_word_ending_before_it_starts_is_rejected():
    with pytest.raises(ValidationError, match="before start"):
        word(start=2.0, end=1.0)


def test_confidence_outside_zero_to_one_is_rejected():
    with pytest.raises(ValidationError):
        word(confidence=1.2)


def test_segment_needs_at_least_one_word():
    with pytest.raises(ValidationError):
        segment(words=[])


def test_document_is_always_labelled_as_ai_generated():
    document = TranscriptDocument(language="pt", segments=[segment()])

    restored = TranscriptDocument.model_validate_json(document.model_dump_json())
    assert restored.ai_generated is True
    assert restored.segments[0].words[0].text == "olá"
    with pytest.raises(ValidationError):
        TranscriptDocument(ai_generated=False, language="pt", segments=[segment()])


def test_output_records_both_models_and_the_counts():
    output = TranscriptionOutput(
        transcript_key="transcript/transcript.json",
        language="pt",
        model_name="large-v3-turbo",
        model_revision="a" * 40,
        alignment_model_name="jonatasgrosman/wav2vec2-large-xlsr-53-portuguese",
        alignment_model_revision="b" * 40,
        parameters={"beam_size": 5},
        time_offset_seconds=0.0,
        segment_count=1,
        word_count=1,
        aligned_word_count=1,
    )

    assert TranscriptionOutput.model_validate(output.model_dump(mode="json")) == output
