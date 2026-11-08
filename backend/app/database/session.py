from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """One engine per process, created on first use so importing this module needs no database."""
    settings = get_settings()
    return create_engine(settings.database_url, echo=settings.database_echo, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one short-lived session per request."""
    with get_session_factory()() as session:
        yield session
