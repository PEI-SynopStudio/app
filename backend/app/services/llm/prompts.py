import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Tuple

from app.core.config import (
    ERROR_FILE_NOT_FOUND,
    ERROR_PROMPT_INVALID_PLACEHOLDER,
    ERROR_PROMPT_VARIABLES,
    PROMPT_CONTROL_CHARACTERS_PATTERN,
    PROMPT_FILE_ENCODING,
    PROMPT_SYSTEM_SUFFIX,
    PROMPT_TEXT_SEPARATOR,
    PROMPT_USER_SUFFIX,
    PROMPT_VERSION_LENGTH,
    PROMPT_VERSION_SEPARATOR,
    PROMPTS_DIR,
)

_CONTROL_CHARACTERS = re.compile(PROMPT_CONTROL_CHARACTERS_PATTERN)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str  # first PROMPT_VERSION_LENGTH hex characters of the SHA-256 of both files
    system: str
    user: str


# Fills the two files of a prompt with the given variables.
# Source: docs/llm-contract.md §7.4 (prompts in files; the version is recorded with every AI output, FR16, FR18).
def render_prompt(name: str, **variables: str) -> Prompt:
    """Reads app/prompts/{name}.system.txt and {name}.user.txt and fills $variables with string.Template.

    A missing variable raises ValueError; an unused one too, so prompt files and code cannot drift apart.
    """
    system, user, version = _load_prompt(PROMPTS_DIR, name)
    expected = set(system.get_identifiers()) | set(user.get_identifiers())
    missing = sorted(expected - variables.keys())
    unused = sorted(variables.keys() - expected)
    if missing or unused:
        raise ValueError(ERROR_PROMPT_VARIABLES.format(name=name, missing=missing, unused=unused))
    return Prompt(name=name, version=version, system=system.substitute(variables), user=user.substitute(variables))


# Keeps user text (clip topic, audience) inside its delimited block of the prompt.
# Source: docs/llm-contract.md §7.4 (prompt injection).
def clean_user_text(text: str) -> str:
    """Replaces control characters and line breaks with one space and strips both ends.

    The length is already limited by ClipOptions; an option that is not set (None) is handled by the caller.
    """
    return _CONTROL_CHARACTERS.sub(PROMPT_TEXT_SEPARATOR, text).strip()


@lru_cache(maxsize=None)
def _load_prompt(directory: Path, name: str) -> Tuple[Template, Template, str]:
    """Reads the two files once per process and computes the version over both."""
    contents = []
    for suffix in (PROMPT_SYSTEM_SUFFIX, PROMPT_USER_SUFFIX):
        path = directory / f"{name}{suffix}"
        if not path.is_file():
            raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=path))
        contents.append(path.read_bytes())
    templates = [Template(content.decode(PROMPT_FILE_ENCODING)) for content in contents]
    if not all(template.is_valid() for template in templates):
        raise ValueError(ERROR_PROMPT_INVALID_PLACEHOLDER.format(name=name))
    version = hashlib.sha256(PROMPT_VERSION_SEPARATOR.join(contents)).hexdigest()[:PROMPT_VERSION_LENGTH]
    return templates[0], templates[1], version
