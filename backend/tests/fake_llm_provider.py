from typing import Callable, Dict, List, Mapping, Sequence, Union

from app.schemas.clips import LLMInfo
from app.services.llm.provider import LLMProvider, LLMReply, LLMRequest

Scripted = Union[str, Exception, Callable[[LLMRequest], str]]

FAKE_INFO = LLMInfo(provider="fake", model="fake-model")


class FakeLLMProvider(LLMProvider):
    """Replies with scripted text per prompt name, in order, and records every request it receives."""

    def __init__(self, replies: Mapping[str, Sequence[Scripted]], info: LLMInfo = FAKE_INFO) -> None:
        self._replies: Dict[str, List[Scripted]] = {name: list(items) for name, items in replies.items()}
        self._info = info
        self.requests: List[LLMRequest] = []

    @property
    def info(self) -> LLMInfo:
        return self._info

    def generate(self, request: LLMRequest) -> LLMReply:
        self.requests.append(request)
        remaining = self._replies.get(request.prompt_name)
        assert remaining, f"No scripted reply left for prompt {request.prompt_name!r}"
        item = remaining.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMReply(text=item(request) if callable(item) else item)
