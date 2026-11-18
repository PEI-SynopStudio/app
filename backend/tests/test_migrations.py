import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.base import utc_now
from test_models import make_asset, make_project

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


INSERT_UPLOAD_AT_0003 = text(
    "INSERT INTO upload_sessions (id, project_id, media_asset_id, file_name, size_bytes, chunk_size, total_chunks, "
    "staged_file, expires_at, created_at) VALUES (:id, :project_id, :asset_id, 'a.mp4', 10, 4, 3, 'a.mp4', :now, :now)"
)


def insert_entry(engine, age=timedelta()):
    entry_id = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.execute(INSERT_ENTRY, {"id": entry_id, "created_at": utc_now() - age})
    return entry_id


def test_migrations_match_the_models(alembic_config):
    command.check(alembic_config)


def test_uploads_in_progress_are_discarded_when_the_chunks_move_to_object_storage(alembic_config, engine):
    command.downgrade(alembic_config, "0003")
    with Session(engine) as db:
        project = make_project()
        asset = make_asset(project)
        db.add_all([project, asset])
        db.commit()
        db.execute(INSERT_UPLOAD_AT_0003, {
            "id": str(uuid.uuid4()), "project_id": str(project.id), "asset_id": str(asset.id), "now": utc_now()
        })
        db.commit()

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM upload_sessions")) == 0
        assert connection.scalar(text("SELECT count(*) FROM media_assets")) == 0
        assert connection.scalar(text("SELECT count(*) FROM projects")) == 1


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
