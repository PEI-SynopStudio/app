from datetime import datetime, timezone
from enum import Enum
from typing import Type

from sqlalchemy import DateTime, Enum as SqlEnum, MetaData
from sqlalchemy.orm import DeclarativeBase

from app.core.config import DB_NAMING_CONVENTION, ENUM_COLUMN_LENGTH


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=DB_NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}


def enum_type(enum_class: Type[Enum]) -> SqlEnum:
    """Store an enum by value in a string column, so a new value needs no database type change."""
    return SqlEnum(
        enum_class,
        native_enum=False,
        length=ENUM_COLUMN_LENGTH,
        values_callable=lambda members: [member.value for member in members],
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
