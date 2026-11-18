import pytest
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.database.base import Base
from app.database.session import get_db, get_engine, get_session_factory


def _clear_caches():
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
def configured_url(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("DATABASE_ECHO", raising=False)
    _clear_caches()
    yield database_url
    get_engine().dispose()
    _clear_caches()


def test_base_is_declarative():
    assert issubclass(Base, DeclarativeBase)


def test_engine_uses_configured_url(configured_url):
    assert get_engine().url.render_as_string(hide_password=False) == configured_url


def test_sql_echo_is_off_by_default(configured_url):
    assert get_engine().echo is False


def test_sql_echo_can_be_enabled(configured_url, monkeypatch):
    monkeypatch.setenv("DATABASE_ECHO", "true")

    assert get_engine().echo is True


def test_get_db_yields_a_working_session_and_closes_it(configured_url):
    dependency = get_db()
    session = next(dependency)

    assert session.execute(text("SELECT 1")).scalar_one() == 1

    dependency.close()
    assert not session.in_transaction()
