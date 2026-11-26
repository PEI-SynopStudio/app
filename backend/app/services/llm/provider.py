from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from app.core.config import LLMRoleEnum
from app.schemas.clips import LLMInfo


@dataclass(frozen=True)
class LLMMessage:
    role: LLMRoleEnum  # system, user, assistant
    content: str


@dataclass(frozen=True)
class LLMRequest:
    prompt_name: str
    prompt_version: str
    messages: Sequence[LLMMessage]
    json_schema: Dict[str, Any]  # schema.model_json_schema() of the expected reply


@dataclass(frozen=True)
class LLMReply:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


# One request to a model, without retries or validation; LLMClient adds both.
# Source: NFR Maintainability (≥ 2 swappable LLM providers, configuration only).
class LLMProvider(ABC):

    @property
    @abstractmethod
    def info(self) -> LLMInfo:
        """Provider kind and model name, recorded with every AI output (FR16, FR18)."""

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMReply:
        """Blocking. Asks the server for JSON constrained to request.json_schema when it supports it
        (Ollama `format`, OpenAI-compatible `response_format` with `json_schema`).

        Raises LLMUnavailableError on connection errors, timeouts, HTTP 429/5xx or a missing model.
        """
