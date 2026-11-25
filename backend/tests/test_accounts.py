import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import REAUTHENTICATION_REQUIRED_CODE, AuditAction, JobTypeEnum, get_settings
from app.database.base import utc_now
from app.database.models import AuditLog, AuthSession, Job, Project, User
from app.main import app
from app.services.auth.auth import actor_hash
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import get_object_storage
from conftest import sign_in
from in_memory_object_storage import InMemoryObjectStorage

PROJECT_BODY = {
    "title": "Debate",
    "author": "University of Aveiro",
    "speakers": ["Ana"],
    "recording_date": "2026-10-01",
    "license_type": "creative_commons",
    "copyright_notice": "CC BY 4.0",
    "licence_confirmed": True,
    "authorship_confirmed": True,
}


@pytest.fixture
def object_storage():
    return InMemoryObjectStorage()


@pytest.fixture
def client(db_override, identity_provider, tmp_path, object_storage, session_factory, user):
    """Signed in just now, so the account can be deleted without signing in again."""
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path / "media")
    app.dependency_overrides[get_object_storage] = lambda: object_storage
    yield sign_in(TestClient(app), session_factory, user)
    app.dependency_overrides.clear()


def delete_account(client):
    return client.delete("/auth/me")


def test_deleting_the_account_removes_it_here_and_at_keycloak_and_keeps_the_audit_log(
    client, db, object_storage, identity_provider, user
):
    project_id = client.post("/projects", json=PROJECT_BODY).json()["id"]
    object_storage.objects[(project_id, "proxy/proxy.mp4")] = b"x"

    response = delete_account(client)

    assert response.status_code == 204
    assert client.get("/auth/me").status_code == 401
    assert identity_provider.deleted_accounts == ["subject-1"]
    db.expire_all()
    assert db.get(User, user.id) is None
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert db.scalar(select(func.count()).select_from(Project)) == 0
    assert object_storage.objects == {}
    entry = db.scalar(select(AuditLog).where(AuditLog.action == AuditAction.PROJECT_DELETED))
    assert (str(entry.project_id), entry.actor_hash) == (project_id, actor_hash(user.id))


def test_deleting_the_account_needs_a_recent_sign_in(client, db, identity_provider, session_factory, user):
    too_old = utc_now() - timedelta(seconds=get_settings().reauth_max_age_seconds + 1)
    browser = sign_in(TestClient(app), session_factory, user, authenticated_at=too_old)

    response = delete_account(browser)

    assert (response.status_code, response.json()["detail"]) == (403, REAUTHENTICATION_REQUIRED_CODE)
    assert identity_provider.deleted_accounts == []
    assert db.get(User, user.id) is not None


def test_an_account_with_a_running_ingestion_cannot_be_deleted(client, db, identity_provider):
    project_id = client.post("/projects", json=PROJECT_BODY).json()["id"]
    db.add(Job(project_id=uuid.UUID(project_id), job_type=JobTypeEnum.INGESTION, parameters={}))
    db.commit()

    assert delete_account(client).status_code == 409
    assert client.get(f"/projects/{project_id}").status_code == 200
    assert identity_provider.deleted_accounts == []


def test_keycloak_down_keeps_the_account_so_the_deletion_can_be_repeated(client, db, identity_provider, user):
    identity_provider.unavailable = True

    assert delete_account(client).status_code == 503
    assert client.get("/auth/me").status_code == 200

    identity_provider.unavailable = False
    assert delete_account(client).status_code == 204
    db.expire_all()
    assert db.get(User, user.id) is None
