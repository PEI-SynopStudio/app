import os
import tomllib
from functools import lru_cache
from typing import Callable, Dict, Optional

from pydantic import BaseModel, ConfigDict

from app.core.config import (
    DEFAULT_LLM_CONTEXT_TOKENS,
    DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    DEFAULT_LLM_SEED,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_LLM_THINK,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    ERROR_FILE_NOT_FOUND,
    ERROR_LLM_API_KEY_MISSING,
    ERROR_LLM_PROFILE_UNKNOWN,
    ERROR_LLM_PROVIDER_UNKNOWN,
    LLM_CONFIG_FILE_ENCODING,
    LLMSettings,
    LlmProviderEnum,
    get_settings,
)
from app.services.llm.ollama import OllamaProvider
from app.services.llm.openai_compatible import OpenAICompatibleProvider
from app.services.llm.provider import LLMProvider

_PROVIDERS: Dict[LlmProviderEnum, Callable[[LLMSettings], LLMProvider]] = {
    LlmProviderEnum.OLLAMA: OllamaProvider,
    LlmProviderEnum.OPENAI_COMPATIBLE: OpenAICompatibleProvider,
}


class _Profile(BaseModel):
    """One [profiles.<name>] table of llm.toml; an unknown field is a typo and is refused."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    base_url: str
    model: str
    api_key_env: Optional[str] = None
    context_tokens: int = DEFAULT_LLM_CONTEXT_TOKENS
    max_output_tokens: int = DEFAULT_LLM_MAX_OUTPUT_TOKENS
    temperature: float = DEFAULT_LLM_TEMPERATURE
    seed: int = DEFAULT_LLM_SEED
    timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    think: bool = DEFAULT_LLM_THINK


class _ConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_profile: str
    profiles: Dict[str, _Profile]


# Resolves the LLM profile chosen by configuration only: environment variable > profile in llm.toml > default.
# Source: docs/llm-contract.md §7.5 (NFR Maintainability, ≥ 2 swappable providers).
@lru_cache
def get_llm_settings() -> LLMSettings:
    """Reads LLM_CONFIG_FILE once per process (call get_llm_settings.cache_clear() after changing env or the file).

    Raises ValueError for an unknown profile, field or provider kind and for a missing API key, so the worker
    fails at start-up instead of at its first job; FileNotFoundError when the file does not exist.
    """
    settings = get_settings()
    path = settings.llm_config_file
    if not path.is_file():
        raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=path))
    config = _ConfigFile.model_validate(tomllib.loads(path.read_text(encoding=LLM_CONFIG_FILE_ENCODING)))
    name = settings.llm_profile or config.default_profile
    profile = config.profiles.get(name)
    if profile is None:
        raise ValueError(ERROR_LLM_PROFILE_UNKNOWN.format(profile=name, path=path, available=sorted(config.profiles)))
    try:
        provider = LlmProviderEnum(profile.provider)
    except ValueError as exc:
        allowed = [kind.value for kind in LlmProviderEnum]
        raise ValueError(
            ERROR_LLM_PROVIDER_UNKNOWN.format(provider=profile.provider, profile=name, allowed=allowed)
        ) from exc
    api_key = None
    if profile.api_key_env is not None:
        api_key = os.environ.get(profile.api_key_env)
        if not api_key:
            raise ValueError(ERROR_LLM_API_KEY_MISSING.format(profile=name, variable=profile.api_key_env))
    return LLMSettings(
        profile=name,
        provider=provider,
        base_url=settings.llm_base_url or profile.base_url,
        model=settings.llm_model or profile.model,
        context_tokens=profile.context_tokens,
        max_output_tokens=profile.max_output_tokens,
        temperature=profile.temperature,
        seed=profile.seed,
        timeout_seconds=(
            settings.llm_timeout_seconds if settings.llm_timeout_seconds is not None else profile.timeout_seconds
        ),
        think=profile.think,
        api_key=api_key,
    )


# Builds the provider of the configured profile; the clip worker calls it once at start-up.
# Source: docs/llm-contract.md §7.5.
def get_llm_provider() -> LLMProvider:
    """There is no fake provider in the application: the fake lives in the tests."""
    settings = get_llm_settings()
    return _PROVIDERS[settings.provider](settings)
