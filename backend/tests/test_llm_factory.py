"""LLM profiles from llm.toml and the environment (docs/llm-contract.md §7.5)."""
import pytest

from app.core.config import (
    DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    DEFAULT_LLM_SEED,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_LLM_THINK,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    LLMSettings,
    LlmProviderEnum,
    get_settings,
)
from app.services.llm.factory import get_llm_provider, get_llm_settings
from app.services.llm.ollama import OllamaProvider
from app.services.llm.openai_compatible import OpenAICompatibleProvider

LLM_VARIABLES = (
    "LLM_CONFIG_FILE",
    "LLM_PROFILE",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_API_KEY",
    "TEST_LLM_KEY",
)
PROFILES = """
default_profile = "local"

[profiles.local]
provider = "ollama"
base_url = "http://ollama:11434"
model = "qwen3:1.7b"
context_tokens = 8192
timeout_seconds = 120

[profiles.remote]
provider = "openai_compatible"
base_url = "http://vllm:8000/v1"
model = "Qwen/Qwen3-8B"
api_key_env = "TEST_LLM_KEY"
think = true
"""


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in LLM_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    get_llm_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_llm_settings.cache_clear()


@pytest.fixture
def use_profiles(tmp_path, monkeypatch):
    def write(text=PROFILES):
        path = tmp_path / "llm.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("LLM_CONFIG_FILE", str(path))

    return write


def test_default_profile_with_the_defaults_of_config(use_profiles):
    use_profiles()

    assert get_llm_settings() == LLMSettings(
        profile="local",
        provider=LlmProviderEnum.OLLAMA,
        base_url="http://ollama:11434",
        model="qwen3:1.7b",
        context_tokens=8192,
        max_output_tokens=DEFAULT_LLM_MAX_OUTPUT_TOKENS,
        temperature=DEFAULT_LLM_TEMPERATURE,
        seed=DEFAULT_LLM_SEED,
        timeout_seconds=120,
        think=DEFAULT_LLM_THINK,
    )


def test_profile_chosen_by_the_environment(use_profiles, monkeypatch):
    use_profiles()
    monkeypatch.setenv("LLM_PROFILE", "remote")
    monkeypatch.setenv("TEST_LLM_KEY", "secret-key")

    settings = get_llm_settings()

    assert (settings.profile, settings.provider, settings.model) == (
        "remote",
        LlmProviderEnum.OPENAI_COMPATIBLE,
        "Qwen/Qwen3-8B",
    )
    assert (settings.api_key, settings.think, settings.timeout_seconds) == ("secret-key", True, DEFAULT_LLM_TIMEOUT_SECONDS)


def test_environment_overrides_the_profile(use_profiles, monkeypatch):
    use_profiles()
    monkeypatch.setenv("LLM_BASE_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("LLM_MODEL", "qwen3:0.6b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "300")

    settings = get_llm_settings()

    assert (settings.base_url, settings.model, settings.timeout_seconds) == (
        "http://host.docker.internal:11434",
        "qwen3:0.6b",
        300.0,
    )


def test_empty_variables_count_as_unset(use_profiles, monkeypatch):
    use_profiles()
    for name in ("LLM_PROFILE", "LLM_BASE_URL", "LLM_MODEL", "LLM_TIMEOUT_SECONDS"):
        monkeypatch.setenv(name, "")

    settings = get_llm_settings()

    assert (settings.profile, settings.base_url, settings.model, settings.timeout_seconds) == (
        "local",
        "http://ollama:11434",
        "qwen3:1.7b",
        120,
    )


def test_unknown_profile_is_refused(use_profiles, monkeypatch):
    use_profiles()
    monkeypatch.setenv("LLM_PROFILE", "cloud")

    with pytest.raises(ValueError, match="Unknown LLM profile 'cloud'"):
        get_llm_settings()


def test_unknown_provider_kind_is_refused(use_profiles):
    use_profiles(PROFILES.replace('provider = "ollama"', 'provider = "llamafile"'))

    with pytest.raises(ValueError, match="Unknown LLM provider 'llamafile' in profile 'local'"):
        get_llm_settings()


def test_unknown_profile_field_is_refused(use_profiles):
    use_profiles(PROFILES.replace("context_tokens = 8192", "context_tokens = 8192\ntemprature = 0.5"))

    with pytest.raises(ValueError, match="temprature"):
        get_llm_settings()


@pytest.mark.parametrize("key", [None, ""])
def test_missing_api_key_is_refused(use_profiles, monkeypatch, key):
    use_profiles()
    monkeypatch.setenv("LLM_PROFILE", "remote")
    if key is not None:
        monkeypatch.setenv("TEST_LLM_KEY", key)

    with pytest.raises(ValueError, match="TEST_LLM_KEY"):
        get_llm_settings()


def test_missing_file_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CONFIG_FILE", str(tmp_path / "missing.toml"))

    with pytest.raises(FileNotFoundError, match="missing.toml"):
        get_llm_settings()


def test_the_api_key_is_never_shown(use_profiles, monkeypatch):
    use_profiles()
    monkeypatch.setenv("LLM_PROFILE", "remote")
    monkeypatch.setenv("TEST_LLM_KEY", "secret-key")

    assert "secret-key" not in repr(get_llm_settings())


@pytest.mark.parametrize(
    "profile, provider_class",
    [("local", OllamaProvider), ("remote", OpenAICompatibleProvider)],
)
def test_builds_the_provider_of_the_profile(use_profiles, monkeypatch, profile, provider_class):
    use_profiles()
    monkeypatch.setenv("LLM_PROFILE", profile)
    monkeypatch.setenv("TEST_LLM_KEY", "secret-key")

    assert isinstance(get_llm_provider(), provider_class)


@pytest.mark.parametrize(
    "profile, provider, model",
    [
        ("ollama-qwen", LlmProviderEnum.OLLAMA, "qwen3:8b"),
        ("ollama-small", LlmProviderEnum.OLLAMA, "qwen3:1.7b"),
        ("openai-compatible", LlmProviderEnum.OPENAI_COMPATIBLE, "Qwen/Qwen3-8B"),
    ],
)
def test_the_project_file_holds_the_contract_profiles(monkeypatch, profile, provider, model):
    monkeypatch.setenv("LLM_PROFILE", profile)
    monkeypatch.setenv("LLM_API_KEY", "secret-key")

    settings = get_llm_settings()

    assert (settings.provider, settings.model) == (provider, model)


def test_the_project_default_profile_is_the_vm_model():
    assert get_llm_settings().profile == "ollama-qwen"
