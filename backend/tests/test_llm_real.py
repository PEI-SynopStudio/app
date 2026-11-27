"""Optional check against a real model (docs/llm-contract.md §17): skipped unless TEST_LLM_PROFILE is set.

It never runs in CI. Set TEST_LLM_PROFILE to a profile of app/core/llm.toml, plus LLM_BASE_URL when the server is
not at the profile's address (README, "LLM (Ollama)").
"""
import os
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.schemas.clips import CandidateReply
from app.services.llm import prompts
from app.services.llm.client import LLMClient
from app.services.llm.factory import get_llm_provider, get_llm_settings
from app.services.llm.prompts import render_prompt

TEST_LLM_PROFILE = os.environ.get("TEST_LLM_PROFILE")
TEST_PROMPTS = Path(__file__).parent / "data" / "llm" / "prompts"
SENTENCES = "\n".join(
    [
        "[0] (00:00, 4s) Bom dia a todos.",
        "[1] (00:04, 6s) Hoje vamos falar da inflação em 2024.",
        "[2] (00:10, 5s) Foi mais baixa do que o esperado.",
        "[3] (00:15, 7s) Isto deve-se sobretudo a três fatores.",
    ]
)

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not TEST_LLM_PROFILE, reason="set TEST_LLM_PROFILE to run against a real model"),
]


class Title(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LLM_PROFILE", TEST_LLM_PROFILE)
    monkeypatch.setattr(prompts, "PROMPTS_DIR", TEST_PROMPTS)
    get_settings.cache_clear()
    get_llm_settings.cache_clear()
    yield LLMClient(get_llm_provider())
    get_settings.cache_clear()
    get_llm_settings.cache_clear()


def test_real_model_returns_valid_json_and_reports_tokens(client):
    prompt = render_prompt("short_title", language="pt-PT", text=SENTENCES)

    reply = client.complete_json(prompt, Title)

    assert reply.title.strip()
    record = client.calls[0]
    assert record.succeeded
    assert (record.provider, record.model) == (client.info.provider, client.info.model)
    assert record.input_tokens and record.output_tokens


def test_real_server_accepts_the_nested_schemas_of_the_contract(client):
    prompt = render_prompt("pick_excerpt", language="pt-PT", sentences=SENTENCES)

    reply = client.complete_json(prompt, CandidateReply)

    assert isinstance(reply, CandidateReply)
    assert client.calls[0].succeeded
