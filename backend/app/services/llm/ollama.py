from typing import Any, Dict, Optional

import httpx
import ollama
from langchain_ollama import ChatOllama

from app.core.config import (
    ERROR_LLM_REQUEST_FAILED,
    ERROR_LLM_SERVER_UNAVAILABLE,
    HTTP_SERVER_ERROR_MIN_STATUS,
    LLM_UNAVAILABLE_STATUS_CODES,
    OLLAMA_STREAM_ERROR_STATUS,
    LLMSettings,
    LlmProviderEnum,
)
from app.schemas.clips import LLMInfo
from app.services.llm.errors import LLMError, LLMUnavailableError
from app.services.llm.provider import LLMProvider, LLMReply, LLMRequest


class OllamaProvider(LLMProvider):
    """A model served by Ollama, through LangChain's ChatOllama.

    LangChain is imported only here and in openai_compatible.py; the rest of the code talks to LLMClient.
    """

    def __init__(self, settings: LLMSettings, transport: Optional[httpx.BaseTransport] = None) -> None:
        """transport replaces the network in tests (httpx.MockTransport)."""
        client_kwargs: Dict[str, Any] = {"timeout": settings.timeout_seconds}
        if transport is not None:
            client_kwargs["transport"] = transport
        self._settings = settings
        self._info = LLMInfo(provider=LlmProviderEnum.OLLAMA.value, model=settings.model)
        # num_ctx is always set: Ollama's own default is small and silently cuts long prompts.
        self._model = ChatOllama(
            model=settings.model,
            base_url=settings.base_url,
            num_ctx=settings.context_tokens,
            num_predict=settings.max_output_tokens,
            temperature=settings.temperature,
            seed=settings.seed,
            reasoning=settings.think,
            client_kwargs=client_kwargs,
        )

    @property
    def info(self) -> LLMInfo:
        return self._info

    # One chat request with the reply constrained to the JSON schema (Ollama `format`); retries are LLMClient's.
    # Source: docs/llm-contract.md §7.1 and §7.5.
    def generate(self, request: LLMRequest) -> LLMReply:
        """Blocking. Raises LLMUnavailableError on connection errors, timeouts, a missing model, HTTP 429 or 5xx
        and errors reported inside the stream; LLMError on any other refusal.
        """
        messages = [{"role": message.role.value, "content": message.content} for message in request.messages]
        try:
            reply = self._model.invoke(messages, format=request.json_schema)
        except (ConnectionError, httpx.TransportError) as exc:
            raise LLMUnavailableError(self._describe(ERROR_LLM_SERVER_UNAVAILABLE, exc)) from exc
        except ollama.ResponseError as exc:
            if (
                exc.status_code in LLM_UNAVAILABLE_STATUS_CODES
                or exc.status_code == OLLAMA_STREAM_ERROR_STATUS
                or exc.status_code >= HTTP_SERVER_ERROR_MIN_STATUS
            ):
                raise LLMUnavailableError(self._describe(ERROR_LLM_SERVER_UNAVAILABLE, exc)) from exc
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
