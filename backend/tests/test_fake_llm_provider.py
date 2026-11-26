import pytest

from app.core.config import LLMRoleEnum
from app.services.llm.errors import LLMUnavailableError
from app.services.llm.provider import LLMMessage, LLMRequest
from fake_llm_provider import FakeLLMProvider


def request(prompt_name="topic_segmentation", text="[0] (00:00, 3s) Bom dia a todos."):
    return LLMRequest(
        prompt_name=prompt_name,
        prompt_version="test",
        messages=[LLMMessage(role=LLMRoleEnum.USER, content=text)],
        json_schema={},
    )


def test_replies_in_order_and_records_requests():
    provider = FakeLLMProvider({"topic_segmentation": ['{"topics": []}', '{"topics": [1]}']})

    first = provider.generate(request())
    second = provider.generate(request())

    assert (first.text, second.text) == ('{"topics": []}', '{"topics": [1]}')
    assert len(provider.requests) == 2


def test_raises_scripted_errors_and_builds_replies_from_the_request():
    provider = FakeLLMProvider(
        {"clip_candidates": [LLMUnavailableError("down"), lambda sent: sent.messages[-1].content.upper()]}
    )

    with pytest.raises(LLMUnavailableError):
        provider.generate(request("clip_candidates"))
    assert provider.generate(request("clip_candidates", text="olá")).text == "OLÁ"


def test_fails_when_no_reply_is_left():
    provider = FakeLLMProvider({"clip_rating": []})

    with pytest.raises(AssertionError, match="clip_rating"):
        provider.generate(request("clip_rating"))
