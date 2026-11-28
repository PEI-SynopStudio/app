"""OllamaProvider against a scripted Ollama server (httpx.MockTransport): no network, no model."""
import dataclasses
import json

import httpx
import pytest

from app.core.config import LLMRoleEnum, LLMSettings, LlmProviderEnum
from app.schemas.clips import LLMInfo
from app.services.llm.errors import LLMError, LLMUnavailableError
from app.services.llm.ollama import OllamaProvider
from app.services.llm.provider import LLMMessage, LLMReply, LLMRequest

SETTINGS = LLMSettings(
    profile="ollama-small",
    provider=LlmProviderEnum.OLLAMA,
    base_url="http://ollama:11434",
    model="qwen3:1.7b",
    context_tokens=8192,
    max_output_tokens=512,
    temperature=0.0,
    seed=42,
    timeout_seconds=30.0,
    think=False,
)
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
REQUEST = LLMRequest(
    prompt_name="short_title",
    prompt_version="0123456789ab",
    messages=(LLMMessage(LLMRoleEnum.SYSTEM, "Answer with JSON."), LLMMessage(LLMRoleEnum.USER, "Texto: Bom dia.")),
    json_schema=SCHEMA,
)


def stream(*pieces):
    """An Ollama chat stream: one line per piece of the reply, then the final line with the token counts."""
    line = {"model": SETTINGS.model, "created_at": "2026-11-26T10:00:00Z", "done": False}
    lines = [{**line, "message": {"role": "assistant", "content": piece}} for piece in pieces]
    lines.append(
        {
            **line,
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 42,
            "eval_count": 7,
        }
    )
    return httpx.Response(200, content="\n".join(json.dumps(item) for item in lines))


def provider_for(handler, settings=SETTINGS):
    return OllamaProvider(settings, transport=httpx.MockTransport(handler))


def refuse(request):
    raise httpx.ConnectError("connection refused")


def time_out(request):
    raise httpx.ReadTimeout("timed out")


def test_sends_the_messages_schema_and_options():
    sent = []

    def ollama(request):
        sent.append(request)
        return stream('{"title": ', '"Saudação"}')

    reply = provider_for(ollama).generate(REQUEST)

    assert reply == LLMReply(text='{"title": "Saudação"}', input_tokens=42, output_tokens=7)
    assert str(sent[0].url) == "http://ollama:11434/api/chat"
    body = json.loads(sent[0].content)
    assert body["model"] == "qwen3:1.7b"
    assert body["messages"] == [
        {"role": "system", "content": "Answer with JSON."},
        {"role": "user", "content": "Texto: Bom dia."},
    ]
    assert body["format"] == SCHEMA
    assert body["think"] is False
    assert body["options"] == {"num_ctx": 8192, "num_predict": 512, "temperature": 0.0, "seed": 42}


def test_reasoning_follows_the_profile():
    sent = []

    def ollama(request):
        sent.append(json.loads(request.content))
        return stream("{}")

    provider_for(ollama, dataclasses.replace(SETTINGS, think=True)).generate(REQUEST)

    assert sent[0]["think"] is True


def test_info_names_the_provider_and_model():
    assert provider_for(lambda request: stream("{}")).info == LLMInfo(provider="ollama", model="qwen3:1.7b")


@pytest.mark.parametrize(
    "handler",
    [
        refuse,
        time_out,
        lambda request: httpx.Response(404, json={"error": "model 'qwen3:1.7b' not found"}),
        lambda request: httpx.Response(429, json={"error": "server busy"}),
        lambda request: httpx.Response(503, json={"error": "loading model"}),
        lambda request: httpx.Response(200, content=json.dumps({"error": "model runner has unexpectedly stopped"})),
    ],
    ids=["refused", "timeout", "missing-model", "busy", "server-error", "stream-error"],
)
def test_unreachable_or_failing_server_is_unavailable(handler):
    with pytest.raises(LLMUnavailableError, match="ollama server at http://ollama:11434"):
        provider_for(handler).generate(REQUEST)


def test_other_refusals_are_llm_errors():
    def bad_request(request):
        return httpx.Response(400, json={"error": "invalid format schema"})

    with pytest.raises(LLMError, match="invalid format schema") as raised:
        provider_for(bad_request).generate(REQUEST)
    assert not isinstance(raised.value, LLMUnavailableError)
