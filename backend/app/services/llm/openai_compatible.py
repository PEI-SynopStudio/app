from typing import Optional

import httpx
import openai
from langchain_openai import ChatOpenAI

from app.core.config import (
    ERROR_LLM_REQUEST_FAILED,
    ERROR_LLM_SERVER_UNAVAILABLE,
    HTTP_SERVER_ERROR_MIN_STATUS,
    LLM_UNAVAILABLE_STATUS_CODES,
    OPENAI_CHAT_TEMPLATE_KWARGS_KEY,
    OPENAI_CLIENT_MAX_RETRIES,
    OPENAI_COMPATIBLE_NO_API_KEY,
    OPENAI_ENABLE_THINKING_KEY,
    OPENAI_RESPONSE_FORMAT_STRICT,
    OPENAI_RESPONSE_FORMAT_TYPE,
    LLMSettings,
    LlmProviderEnum,
)
from app.schemas.clips import LLMInfo
from app.services.llm.errors import LLMError, LLMUnavailableError
from app.services.llm.provider import LLMProvider, LLMReply, LLMRequest


class OpenAICompatibleProvider(LLMProvider):
    """A model on a self-hosted OpenAI-compatible server (vLLM, llama.cpp, LM Studio), through LangChain's ChatOpenAI.

    LangChain is imported only here and in ollama.py; the rest of the code talks to LLMClient. The context size is
    set when the server starts (e.g. vLLM --max-model-len), not per request.
    """

    def __init__(self, settings: LLMSettings, transport: Optional[httpx.BaseTransport] = None) -> None:
        """transport replaces the network in tests (httpx.MockTransport)."""
        self._settings = settings
        self._info = LLMInfo(provider=LlmProviderEnum.OPENAI_COMPATIBLE.value, model=settings.model)
        self._model = ChatOpenAI(
            model=settings.model,
            base_url=settings.base_url,
            api_key=settings.api_key or OPENAI_COMPATIBLE_NO_API_KEY,
            timeout=settings.timeout_seconds,
            temperature=settings.temperature,
            seed=settings.seed,
            max_tokens=settings.max_output_tokens,
            max_retries=OPENAI_CLIENT_MAX_RETRIES,
            use_responses_api=False,  # self-hosted servers only offer Chat Completions
            http_client=None if transport is None else httpx.Client(transport=transport),
        )

    @property
    def info(self) -> LLMInfo:
        return self._info

    # One chat completion with the reply constrained to the JSON schema (`response_format`); retries are LLMClient's.
    # Source: docs/llm-contract.md §7.1 and §7.5.
    def generate(self, request: LLMRequest) -> LLMReply:
        """Blocking. Raises LLMUnavailableError on connection errors, timeouts, a missing model, HTTP 429 or 5xx;
        LLMError on any other refusal. A reply cut by the output limit is returned as it is, like Ollama does, so
        LLMClient treats it as invalid JSON.
        """
        messages = [{"role": message.role.value, "content": message.content} for message in request.messages]
        response_format = {
            "type": OPENAI_RESPONSE_FORMAT_TYPE,
            "json_schema": {
                "name": request.prompt_name,
                "schema": request.json_schema,
                "strict": OPENAI_RESPONSE_FORMAT_STRICT,
            },
        }
        thinking = {OPENAI_CHAT_TEMPLATE_KWARGS_KEY: {OPENAI_ENABLE_THINKING_KEY: self._settings.think}}
        try:
            reply = self._model.invoke(messages, response_format=response_format, extra_body=thinking)
        except openai.LengthFinishReasonError as exc:
            usage = exc.completion.usage
            return LLMReply(
                text=exc.completion.choices[0].message.content or "",
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
            )
        except openai.APIConnectionError as exc:  # timeouts included
            raise LLMUnavailableError(self._describe(ERROR_LLM_SERVER_UNAVAILABLE, exc)) from exc
        except openai.APIStatusError as exc:
            if exc.status_code in LLM_UNAVAILABLE_STATUS_CODES or exc.status_code >= HTTP_SERVER_ERROR_MIN_STATUS:
                raise LLMUnavailableError(self._describe(ERROR_LLM_SERVER_UNAVAILABLE, exc)) from exc
            raise LLMError(self._describe(ERROR_LLM_REQUEST_FAILED, exc)) from exc
        except openai.OpenAIError as exc:
            raise LLMError(self._describe(ERROR_LLM_REQUEST_FAILED, exc)) from exc
        usage = reply.usage_metadata or {}
        return LLMReply(
            text=reply.content,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    def _describe(self, message: str, error: Exception) -> str:
        return message.format(
            provider=self._info.provider, base_url=self._settings.base_url, model=self._info.model, details=error
        )
