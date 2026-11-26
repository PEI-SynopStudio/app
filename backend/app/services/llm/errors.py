class LLMError(RuntimeError):
    """Base class; RuntimeError as AGENTS.md asks for library failures."""


class LLMUnavailableError(LLMError):
    """The server cannot be reached, timed out or does not have the model."""


class LLMInvalidResponseError(LLMError):
    """The reply was not valid JSON for the schema after every allowed attempt."""
