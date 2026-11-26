"""LLMClient with the fake provider: validation, retries, call records and logs (docs/llm-contract.md §7.3)."""
import logging

import pytest
from pydantic import BaseModel, Field

from app.core.config import (
    DEFAULT_JOB_STALLED_AFTER_SECONDS,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    LLM_MAX_ATTEMPTS,
    LLM_UNAVAILABLE_BACKOFF_SECONDS,
    LLM_UNAVAILABLE_RETRIES,
    LLMRoleEnum,
    get_settings,
)
from app.services.llm import client as client_module
from app.services.llm.client import LLMCallRecord, LLMClient
from app.services.llm.errors import LLMError, LLMInvalidResponseError, LLMUnavailableError
from app.services.llm.prompts import Prompt
from app.services.llm.provider import LLMReply
from fake_llm_provider import FAKE_INFO, FakeLLMProvider

PROMPT = Prompt(name="short_title", version="0123456789ab", system="Answer with JSON.", user="Texto: Bom dia a todos.")
VALID = '{"title": "Saudação"}'


class Title(BaseModel):
    title: str = Field(min_length=1)


class CountingProvider(FakeLLMProvider):
    """The fake provider, reporting 100 input and 20 output tokens per reply."""

    def generate(self, request):
        reply = super().generate(request)
        return LLMReply(text=reply.text, input_tokens=100, output_tokens=20)


@pytest.fixture(autouse=True)
def waits(monkeypatch):
    waited = []
    monkeypatch.setattr(client_module, "sleep", waited.append)
    return waited


@pytest.fixture
def log_content(monkeypatch):
    monkeypatch.setenv("LLM_LOG_CONTENT", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def roles_and_texts(request):
    return [(message.role, message.content) for message in request.messages]


def test_returns_the_validated_reply_and_sends_the_prompt_and_schema():
    provider = FakeLLMProvider({"short_title": [VALID]})
    client = LLMClient(provider)

    assert client.complete_json(PROMPT, Title) == Title(title="Saudação")
    request = provider.requests[0]
    assert roles_and_texts(request) == [(LLMRoleEnum.SYSTEM, PROMPT.system), (LLMRoleEnum.USER, PROMPT.user)]
    assert (request.prompt_name, request.prompt_version) == ("short_title", "0123456789ab")
    assert request.json_schema == Title.model_json_schema()
    assert client.info == FAKE_INFO


def test_removes_the_reasoning_block_before_validating():
    provider = FakeLLMProvider({"short_title": ['<think>\nUm título curto: {"title": "x"}\n</think>\n\n' + VALID]})

    assert LLMClient(provider).complete_json(PROMPT, Title) == Title(title="Saudação")


def test_sends_an_invalid_reply_back_with_the_validation_errors():
    provider = FakeLLMProvider({"short_title": ['{"title": ""}', VALID]})
    client = LLMClient(provider)

    assert client.complete_json(PROMPT, Title) == Title(title="Saudação")
    retry = roles_and_texts(provider.requests[1])
    assert retry[:3] == roles_and_texts(provider.requests[0]) + [(LLMRoleEnum.ASSISTANT, '{"title": ""}')]
    assert retry[3][0] == LLMRoleEnum.USER
    assert "- title: String should have at least 1 character" in retry[3][1]
    assert client.calls[0].attempts == 2
    assert client.calls[0].succeeded


def test_broken_json_is_an_invalid_reply():
    provider = FakeLLMProvider({"short_title": ['{"title": "Sauda', VALID]})

    assert LLMClient(provider).complete_json(PROMPT, Title) == Title(title="Saudação")
    assert "- (reply): Invalid JSON" in provider.requests[1].messages[-1].content


def test_fails_after_the_configured_attempts():
    provider = FakeLLMProvider({"short_title": ["not json"] * LLM_MAX_ATTEMPTS})
    client = LLMClient(provider)

    with pytest.raises(LLMInvalidResponseError, match="'short_title' after 3 attempt"):
        client.complete_json(PROMPT, Title)
    assert len(provider.requests) == LLM_MAX_ATTEMPTS
    assert (client.calls[0].attempts, client.calls[0].succeeded) == (LLM_MAX_ATTEMPTS, False)


def test_asks_again_while_the_server_is_unavailable(waits):
    provider = FakeLLMProvider({"short_title": [LLMUnavailableError("down"), VALID]})
    client = LLMClient(provider)

    assert client.complete_json(PROMPT, Title) == Title(title="Saudação")
    assert waits == [LLM_UNAVAILABLE_BACKOFF_SECONDS]
    assert client.calls[0].attempts == 1


def test_gives_up_when_the_server_stays_unavailable(waits):
    provider = FakeLLMProvider({"short_title": [LLMUnavailableError("down")] * (LLM_UNAVAILABLE_RETRIES + 1)})
    client = LLMClient(provider)

    with pytest.raises(LLMUnavailableError):
        client.complete_json(PROMPT, Title)
    assert waits == [LLM_UNAVAILABLE_BACKOFF_SECONDS] * LLM_UNAVAILABLE_RETRIES
    assert not client.calls[0].succeeded


def test_other_provider_errors_are_recorded_and_not_retried(waits):
    provider = FakeLLMProvider({"short_title": [LLMError("bad request")]})
    client = LLMClient(provider)

    with pytest.raises(LLMError, match="bad request"):
        client.complete_json(PROMPT, Title)
    assert waits == []
    assert not client.calls[0].succeeded


def test_records_every_call_with_tokens_and_duration(monkeypatch):
    times = iter([10.0, 12.5, 20.0, 21.0])
    monkeypatch.setattr(client_module, "monotonic", lambda: next(times))
    provider = CountingProvider({"short_title": ['{"title": ""}', VALID, LLMError("bad request")]})
    client = LLMClient(provider)

    client.complete_json(PROMPT, Title)
    with pytest.raises(LLMError):
        client.complete_json(PROMPT, Title)

    assert client.calls == (
        LLMCallRecord("short_title", "0123456789ab", "fake", "fake-model", 2, 2.5, 200, 40, True),
        LLMCallRecord("short_title", "0123456789ab", "fake", "fake-model", 1, 1.0, None, None, False),
    )


def test_logs_one_line_per_call_without_the_texts(caplog):
    caplog.set_level(logging.DEBUG, logger="app.services.llm.client")
    provider = FakeLLMProvider({"short_title": [VALID]})

    LLMClient(provider).complete_json(PROMPT, Title)

    assert [record.levelno for record in caplog.records] == [logging.INFO]
    assert "LLM call short_title (version 0123456789ab) on fake fake-model: succeeded=True" in caplog.text
    assert "Bom dia" not in caplog.text
    assert "Saudação" not in caplog.text


def test_logs_each_text_once_when_enabled(log_content, caplog):
    caplog.set_level(logging.DEBUG, logger="app.services.llm.client")
    provider = FakeLLMProvider({"short_title": ['{"title": ""}', VALID]})

    LLMClient(provider).complete_json(PROMPT, Title)

    assert caplog.text.count(PROMPT.system) == 1
    assert caplog.text.count(PROMPT.user) == 1
    assert caplog.text.count('{"title": ""}') == 1
    assert caplog.text.count("Answer again with only the corrected JSON.") == 1
    assert caplog.text.count(VALID) == 1


def test_worst_case_call_ends_before_the_job_is_considered_stalled():
    per_attempt = (LLM_UNAVAILABLE_RETRIES + 1) * DEFAULT_LLM_TIMEOUT_SECONDS
    per_attempt += LLM_UNAVAILABLE_RETRIES * LLM_UNAVAILABLE_BACKOFF_SECONDS

    assert LLM_MAX_ATTEMPTS * per_attempt < DEFAULT_JOB_STALLED_AFTER_SECONDS
