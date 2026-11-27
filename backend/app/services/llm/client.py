import logging
import re
from dataclasses import dataclass
from time import monotonic, sleep
from typing import List, Optional, Sequence, Tuple, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import (
    ERROR_LLM_INVALID_RESPONSE,
    LLM_MAX_ATTEMPTS,
    LLM_RETRY_FEEDBACK,
    LLM_THINK_BLOCK_PATTERN,
    LLM_UNAVAILABLE_BACKOFF_SECONDS,
    LLM_UNAVAILABLE_RETRIES,
    LLM_VALIDATION_ERROR_FORMAT,
    LLM_VALIDATION_ERROR_SEPARATOR,
    LLM_VALIDATION_LOCATION_SEPARATOR,
    LLM_VALIDATION_ROOT_LOCATION,
    LOG_LLM_CALL,
    LOG_LLM_CONTENT,
    LOG_LLM_UNAVAILABLE_RETRY,
    LLMRoleEnum,
    get_settings,
)
from app.schemas.clips import LLMInfo
from app.services.llm.errors import LLMInvalidResponseError, LLMUnavailableError
from app.services.llm.prompts import Prompt
from app.services.llm.provider import LLMMessage, LLMProvider, LLMReply, LLMRequest

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_THINK_BLOCK = re.compile(LLM_THINK_BLOCK_PATTERN, re.DOTALL)


@dataclass(frozen=True)
class LLMCallRecord:
    prompt_name: str
    prompt_version: str
    provider: str
    model: str
    attempts: int
    duration_seconds: float
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    succeeded: bool


class LLMClient:
    """One per job: it keeps the records of the calls made for that job."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
        self._calls: List[LLMCallRecord] = []
        self._log_content = get_settings().llm_log_content

    @property
    def info(self) -> LLMInfo:
        return self._provider.info

    @property
    def calls(self) -> Tuple[LLMCallRecord, ...]:
        return tuple(self._calls)

    # Asks the model for JSON and returns it validated against the schema; the reply is never repaired.
    # Source: docs/llm-contract.md §7.3 (FR11, FR15, FR18).
    def complete_json(self, prompt: Prompt, schema: Type[T]) -> T:
        """Sends the rendered prompt with schema.model_json_schema() and validates the reply.

        An invalid reply goes back to the model with the validation errors, up to LLM_MAX_ATTEMPTS attempts in
        total, then LLMInvalidResponseError. LLMUnavailableError is retried LLM_UNAVAILABLE_RETRIES times per
        attempt, then re-raised. Every call is recorded and logged, whatever its outcome.
        """
        messages = [LLMMessage(LLMRoleEnum.SYSTEM, prompt.system), LLMMessage(LLMRoleEnum.USER, prompt.user)]
        json_schema = schema.model_json_schema()
        unlogged = list(messages)
        attempts = 0
        input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None
        succeeded = False
        started = monotonic()
        try:
            while attempts < LLM_MAX_ATTEMPTS:
                attempts += 1
                self._log_messages(prompt.name, attempts, unlogged)
                reply = self._generate(LLMRequest(prompt.name, prompt.version, tuple(messages), json_schema))
                input_tokens = _add_tokens(input_tokens, reply.input_tokens)
                output_tokens = _add_tokens(output_tokens, reply.output_tokens)
                self._log_messages(prompt.name, attempts, [LLMMessage(LLMRoleEnum.ASSISTANT, reply.text)])
                text = _THINK_BLOCK.sub("", reply.text).strip()
                try:
                    result = schema.model_validate_json(text)
                except ValidationError as exc:
                    feedback = LLMMessage(LLMRoleEnum.USER, LLM_RETRY_FEEDBACK.format(errors=_describe_errors(exc)))
                    messages += [LLMMessage(LLMRoleEnum.ASSISTANT, text), feedback]
                    unlogged = [feedback]
                    continue
                succeeded = True
                return result
            raise LLMInvalidResponseError(ERROR_LLM_INVALID_RESPONSE.format(prompt=prompt.name, attempts=attempts))
        finally:
            info = self._provider.info
            record = LLMCallRecord(
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                provider=info.provider,
                model=info.model,
                attempts=attempts,
                duration_seconds=monotonic() - started,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                succeeded=succeeded,
            )
            self._calls.append(record)
            logger.info(
                LOG_LLM_CALL,
                record.prompt_name,
                record.prompt_version,
                record.provider,
                record.model,
                record.succeeded,
                record.attempts,
                record.duration_seconds,
                record.input_tokens,
                record.output_tokens,
            )

    def _generate(self, request: LLMRequest) -> LLMReply:
        """Asks the provider, waiting and asking again while the server is unavailable."""
        for _ in range(LLM_UNAVAILABLE_RETRIES):
            try:
                return self._provider.generate(request)
            except LLMUnavailableError as exc:
                logger.warning(LOG_LLM_UNAVAILABLE_RETRY, request.prompt_name, exc, LLM_UNAVAILABLE_BACKOFF_SECONDS)
                sleep(LLM_UNAVAILABLE_BACKOFF_SECONDS)
        return self._provider.generate(request)

    def _log_messages(self, prompt_name: str, attempt: int, messages: Sequence[LLMMessage]) -> None:
        """Logs the texts sent and received, only when LLM_LOG_CONTENT=true (they hold personal data)."""
        if not self._log_content:
            return
        for message in messages:
            logger.debug(LOG_LLM_CONTENT, prompt_name, attempt, message.role.value, message.content)


def _add_tokens(total: Optional[int], count: Optional[int]) -> Optional[int]:
    """Sums token counts over the attempts; None while the provider reports none."""
    return total if count is None else (total or 0) + count


def _describe_errors(error: ValidationError) -> str:
    """One line per validation error, with its place in the reply, for the model to correct."""
    return LLM_VALIDATION_ERROR_SEPARATOR.join(
        LLM_VALIDATION_ERROR_FORMAT.format(
            location=LLM_VALIDATION_LOCATION_SEPARATOR.join(str(part) for part in item["loc"])
            or LLM_VALIDATION_ROOT_LOCATION,
            message=item["msg"],
        )
        for item in error.errors(include_url=False)
    )
