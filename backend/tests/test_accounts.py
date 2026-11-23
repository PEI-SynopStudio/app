import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import AuditAction, JobTypeEnum
from app.database.models import AuditLog, AuthSession, Job, Project, User
from app.main import app
from app.services.auth.auth import actor_hash, create_user
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import get_object_storage
from conftest import TEST_PASSWORD, sign_in
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
def client(db_override, tmp_path, object_storage, session_factory, user):
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path / "media")
    app.dependency_overrides[get_object_storage] = lambda: object_storage
    yield sign_in(TestClient(app), session_factory, user)
    app.dependency_overrides.clear()


def delete_account(client, password=TEST_PASSWORD):
    return client.request("DELETE", "/auth/me", json={"password": password})


def test_the_name_can_be_corrected(client):
    response = client.patch("/auth/me", json={"name": "  Ana Silva "})

    assert response.status_code == 200
    assert client.get("/auth/me").json()["name"] == "Ana Silva"


def test_a_new_email_needs_the_current_password(client):
    missing = client.patch("/auth/me", json={"email": "new@example.com"})
    wrong = client.patch("/auth/me", json={"email": "new@example.com", "current_password": "not-it"})
    accepted = client.patch("/auth/me", json={"email": "New@Example.com", "current_password": TEST_PASSWORD})

    assert (missing.status_code, wrong.status_code, accepted.status_code) == (403, 403, 200)
    assert accepted.json()["email"] == "new@example.com"
    assert client.post("/auth/login", json={"email": "new@example.com", "password": TEST_PASSWORD}).status_code == 200


def test_an_email_in_use_is_refused(client, db):
    create_user(db, "taken@example.com", "Other", TEST_PASSWORD)

    response = client.patch("/auth/me", json={"email": "taken@example.com", "current_password": TEST_PASSWORD})

    assert response.status_code == 409
    assert client.get("/auth/me").json()["email"] == "owner@example.com"


def test_deleting_the_account_removes_its_projects_and_keeps_the_audit_log(client, db, object_storage, user):
    project_id = client.post("/projects", json=PROJECT_BODY).json()["id"]
    object_storage.objects[(project_id, "proxy/proxy.mp4")] = b"x"

    response = delete_account(client)

    assert response.status_code == 204
    assert client.get("/auth/me").status_code == 401
    db.expire_all()
    assert db.get(User, user.id) is None
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert db.scalar(select(func.count()).select_from(Project)) == 0
    assert object_storage.objects == {}
    entry = db.scalar(select(AuditLog).where(AuditLog.action == AuditAction.PROJECT_DELETED))
    assert (str(entry.project_id), entry.actor_hash) == (project_id, actor_hash(user.id))


def test_a_wrong_password_keeps_the_account(client):
    assert delete_account(client, "not-it").status_code == 403
    assert client.get("/auth/me").status_code == 200


def test_an_account_with_a_running_ingestion_cannot_be_deleted(client, db):
    project_id = client.post("/projects", json=PROJECT_BODY).json()["id"]
    db.add(Job(project_id=uuid.UUID(project_id), job_type=JobTypeEnum.INGESTION, parameters={}))
    db.commit()

    assert delete_account(client).status_code == 409
    assert client.get(f"/projects/{project_id}").status_code == 200
