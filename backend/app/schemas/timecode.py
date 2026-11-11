import re
from decimal import Decimal

from app.core.config import (
    ERROR_INVALID_TIMECODE,
    ERROR_TIMECODE_MINUTES,
    ERROR_TIMECODE_SECONDS,
    SEXAGESIMAL_BASE,
    TIMECODE_HMS_PARTS,
    TIMECODE_PART_COUNTS,
    TIMECODE_PART_PATTERN,
    TIMECODE_SEPARATOR,
)

_PART = re.compile(TIMECODE_PART_PATTERN)


def parse_time(value: str) -> Decimal:
    """Convert "SS", "MM:SS" or "HH:MM:SS" (up to 3 decimals) into seconds."""
    parts = value.split(TIMECODE_SEPARATOR)
    if len(parts) not in TIMECODE_PART_COUNTS or not all(_PART.fullmatch(part) for part in parts):
        raise ValueError(ERROR_INVALID_TIMECODE.format(value=value))

    if len(parts) > 1 and Decimal(parts[-1]) >= SEXAGESIMAL_BASE:
        raise ValueError(ERROR_TIMECODE_SECONDS.format(value=value))
    if len(parts) == TIMECODE_HMS_PARTS and Decimal(parts[1]) >= SEXAGESIMAL_BASE:
        raise ValueError(ERROR_TIMECODE_MINUTES.format(value=value))

    return sum(Decimal(part) * SEXAGESIMAL_BASE**index for index, part in enumerate(reversed(parts)))
