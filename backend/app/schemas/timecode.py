from decimal import Decimal
import re

_PART = re.compile(r"\d+(?:\.\d{1,3})?")

def parse_time(value: str) -> Decimal:
    parts = value.split(":")
    if len(parts) not in (1, 2, 3) or not all(_PART.fullmatch(p) for p in parts):
        raise ValueError(f"Formato de tempo invalido: {value}")

    if len(parts) > 1 and Decimal(parts[-1]) >= 60:
        raise ValueError(f"Os segundos devem ser inferiores a 60: {value}")
    if len(parts) == 3 and Decimal(parts[1]) >= 60:
        raise ValueError(f"Os minutos devem ser inferiores a 60: {value}")

    return sum(Decimal(part) * 60**index for index, part in enumerate(reversed(parts)))