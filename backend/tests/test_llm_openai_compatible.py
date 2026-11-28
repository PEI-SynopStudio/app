"""OpenAICompatibleProvider against a scripted server (httpx.MockTransport): no network, no model."""
import dataclasses
import json

import httpx
import pytest

from app.core.config import LLMRoleEnum, LLMSettings, LlmProviderEnum
from app.schemas.clips import LLMInfo
from app.services.llm.errors import LLMError, LLMUnavailableError
from app.services.llm.openai_compatible import OpenAICompatibleProvider
from app.services.llm.provider import LLMMessage, LLMReply, LLMRequest

SETTINGS = LLMSettings(
    profile="openai-compatible",
    provider=LlmProviderEnum.OPENAI_COMPATIBLE,
    base_url="http://vllm:8000/v1",
    model="Qwen/Qwen3-8B",
    context_tokens=16384,
    max_output_tokens=512,
    temperature=0.0,
    seed=42,
    timeout_seconds=30.0,
    think=False,
    api_key="test-key",
)
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
REQUEST = LLMRequest(
    prompt_name="short_title",
    prompt_version="0123456789ab",
    messages=(LLMMessage(LLMRoleEnum.SYSTEM, "Answer with JSON."), LLMMessage(LLMRoleEnum.USER, "Texto: Bom dia.")),
    json_schema=SCHEMA,
)


def completion(content, finish_reason="stop"):
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1764151200,
            "model": SETTINGS.model,
            "choices": [
                {"index": 0, "finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}
            ],
            "usage": {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49},
        },
    )


def provider_for(handler, settings=SETTINGS):
    return OpenAICompatibleProvider(settings, transport=httpx.MockTransport(handler))


def refuse(request):
    raise httpx.ConnectError("connection refused")


def time_out(request):
    raise httpx.ReadTimeout("timed out")


def test_sends_the_messages_schema_and_options():
    sent = []

    def server(request):
        sent.append(request)
        return completion('{"title": "Saudação"}')

    reply = provider_for(server).generate(REQUEST)

    assert reply == LLMReply(text='{"title": "Saudação"}', input_tokens=42, output_tokens=7)
    assert str(sent[0].url) == "http://vllm:8000/v1/chat/completions"
    assert sent[0].headers["authorization"] == "Bearer test-key"
    body = json.loads(sent[0].content)
    assert body["model"] == "Qwen/Qwen3-8B"
    assert body["messages"] == [
        {"role": "system", "content": "Answer with JSON."},
        {"role": "user", "content": "Texto: Bom dia."},
    ]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "short_title", "schema": SCHEMA, "strict": False},
    }
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert (body["seed"], body["temperature"], body["max_completion_tokens"]) == (42, 0.0, 512)


def test_a_server_without_a_key_gets_a_placeholder():
    sent = []

    def server(request):
        sent.append(request)
        return completion("{}")

    provider_for(server, dataclasses.replace(SETTINGS, api_key=None)).generate(REQUEST)

    assert sent[0].headers["authorization"] == "Bearer not-needed"


def test_a_reply_cut_by_the_output_limit_is_returned_as_it_is():
    reply = provider_for(lambda request: completion('{"title": "Sauda', finish_reason="length")).generate(REQUEST)

    assert reply == LLMReply(text='{"title": "Sauda', input_tokens=42, output_tokens=7)


def test_info_names_the_provider_and_model():
    provider = provider_for(lambda request: completion("{}"))

    assert provider.info == LLMInfo(provider="openai_compatible", model="Qwen/Qwen3-8B")


@pytest.mark.parametrize(
    "handler",
    [
        refuse,
        time_out,
        lambda request: httpx.Response(404, json={"error": {"message": "model not found"}}),
        lambda request: httpx.Response(429, json={"error": {"message": "server busy"}}),
        lambda request: httpx.Response(503, json={"error": {"message": "loading model"}}),
    ],
    ids=["refused", "timeout", "missing-model", "busy", "server-error"],
)
def test_unreachable_or_failing_server_is_unavailable(handler):
    with pytest.raises(LLMUnavailableError, match="openai_compatible server at http://vllm:8000/v1"):
        provider_for(handler).generate(REQUEST)


@pytest.mark.parametrize("status", [400, 401])
def test_other_refusals_are_llm_errors(status):
    def refuse_request(request):
        return httpx.Response(status, json={"error": {"message": "request refused"}})

    with pytest.raises(LLMError, match="request refused") as raised:
        provider_for(refuse_request).generate(REQUEST)
    assert not isinstance(raised.value, LLMUnavailableError)
