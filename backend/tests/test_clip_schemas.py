from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import AspectRatioEnum, JobTypeEnum
from app.schemas.clips import ClipOptions, SentenceRange, TopicReply
from app.schemas.job import ClipProposalParams, JobRequestMessage


def test_options_default_to_15_to_60_seconds_in_portrait():
    options = ClipOptions()

    assert (options.min_duration_seconds, options.max_duration_seconds) == (15, 60)
    assert options.aspect_ratio is AspectRatioEnum.PORTRAIT


def test_options_reject_min_above_max():
    with pytest.raises(ValidationError):
        ClipOptions(min_duration_seconds=60, max_duration_seconds=30)


def test_options_reject_durations_outside_5_to_180_seconds():
    with pytest.raises(ValidationError):
        ClipOptions(min_duration_seconds=4)
    with pytest.raises(ValidationError):
        ClipOptions(max_duration_seconds=181)


def test_options_reject_unknown_fields():
    with pytest.raises(ValidationError):
        ClipOptions.model_validate({"topic": "economia", "clip_text": "uma citação inventada"})


def test_range_rejects_last_before_first():
    with pytest.raises(ValidationError):
        SentenceRange(first=5, last=4)


def test_llm_reply_ignores_extra_fields():
    reply = TopicReply.model_validate_json(
        '{"topics": [{"first_sentence": 0, "last_sentence": 9, "title": "Inflação",'
        ' "summary": "As causas da inflação.", "confidence": 0.9}]}'
    )

    assert reply.topics[0].last_sentence == 9


def test_request_message_carries_the_clip_proposal():
    params = ClipProposalParams(transcript_id=uuid4(), options=ClipOptions(topic="economia"))
    msg = JobRequestMessage(
        job_id=uuid4(), project_id=uuid4(), parameters=params, transcript_key="clips/job/transcript.json"
    )

    restored = JobRequestMessage.model_validate_json(msg.model_dump_json())
    assert isinstance(restored.parameters, ClipProposalParams)
    assert restored.parameters.job_type == JobTypeEnum.CLIP_PROPOSAL.value
    assert restored.parameters.options.topic == "economia"
    assert restored.transcript_key == "clips/job/transcript.json"
