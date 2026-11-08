import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.database.base import utc_now

BACKEND_ROOT = Path(__file__).resolve().parent.parent
INSERT_ENTRY = text(
    "INSERT INTO audit_log (id, project_id, action, details, created_at) "
    "VALUES (:id, :id, 'project.created', '{}', :created_at)"
)


@pytest.fixture
def alembic_config(database_url, monkeypatch):
    """Apply every migration on the empty test database and revert them at the end."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    yield config
    command.downgrade(config, "base")
    get_settings.cache_clear()


@pytest.fixture
def engine(alembic_config, database_url):
    instance = create_engine(database_url)
    yield instance
    instance.dispose()


def insert_entry(engine, age=timedelta()):
    entry_id = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.execute(INSERT_ENTRY, {"id": entry_id, "created_at": utc_now() - age})
    return entry_id


def test_migrations_match_the_models(alembic_config):
    command.check(alembic_config)


def test_the_database_refuses_to_change_an_audit_entry(engine):
    entry_id = insert_entry(engine)

    with pytest.raises(DBAPIError, match="cannot be changed"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE audit_log SET actor_hash = 'x' WHERE id = :id"), {"id": entry_id})


def test_the_database_refuses_to_delete_a_recent_audit_entry(engine):
    entry_id = insert_entry(engine)

    with pytest.raises(DBAPIError, match="cannot be changed"):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry_id})


def test_an_audit_entry_can_be_purged_after_12_months(engine):
    entry_id = insert_entry(engine, age=timedelta(days=400))

    with engine.begin() as connection:
        deleted = connection.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry_id})

    assert deleted.rowcount == 1
