from typing import Iterable

from pydantic import BaseModel

from app.core.config import ERROR_FIELD_NOT_NULLABLE


def reject_nulls(model: BaseModel, nullable: Iterable[str]) -> None:
    """In a PATCH body, an omitted field keeps its value; only the `nullable` fields may be sent as null."""
    for field in model.model_fields_set:
        if field not in nullable and getattr(model, field) is None:
            raise ValueError(ERROR_FIELD_NOT_NULLABLE.format(field=field))