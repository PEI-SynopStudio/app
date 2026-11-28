import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import AuditAction, get_settings
from app.database.models import AuditLog, ProjectDocument
from app.main import app
from app.services.storage.object_storage import get_object_storage
from in_memory_object_storage import InMemoryObjectStorage, UnavailableObjectStorage
from test_api_projects import PROJECT_BODY
from app.services.auth.auth import actor_hash
from conftest import sign_in

SLIDES = ("slides.pdf", b"%PDF-1.7 slides", "application/pdf")


@pytest.fixture
def object_storage():
    return InMemoryObjectStorage()


@pytest.fixture
def client(db_override, object_storage, session_factory, user):
    app.dependency_overrides[get_object_storage] = lambda: object_storage
    yield sign_in(TestClient(app), session_factory, user)
    app.dependency_overrides.clear()


@pytest.fixture
def project_id(client):
    return client.post("/projects", json=PROJECT_BODY).json()["id"]


@pytest.fixture
def small_limits(monkeypatch):
    monkeypatch.setenv("MAX_DOCUMENT_BYTES", "10")
    monkeypatch.setenv("MAX_DOCUMENTS_PER_PROJECT", "2")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def documents_url(project_id):
    return f"/projects/{project_id}/documents"


def upload(client, project_id, file=SLIDES):
    return client.post(documents_url(project_id), files={"file": file})


def document_count(db):
    return db.scalar(select(func.count()).select_from(ProjectDocument))


def test_a_document_is_stored_under_a_server_chosen_key(client, project_id, object_storage, db, user):
    response = upload(client, project_id)

    assert response.status_code == 201
    document = response.json()
    assert {key: document[key] for key in ("file_name", "file_type", "content_type", "size_bytes")} == {
        "file_name": "slides.pdf", "file_type": "pdf", "content_type": "application/pdf", "size_bytes": 15
    }
    assert "storage_key" not in document
    assert object_storage.objects == {(project_id, f"documents/{document['id']}.pdf"): b"%PDF-1.7 slides"}
    assert client.get(documents_url(project_id)).json() == [document]
    assert client.get(f"/projects/{project_id}").json()["documents"] == [document]
    [entry] = db.scalars(select(AuditLog).where(AuditLog.action == AuditAction.DOCUMENT_ADDED)).all()
    assert entry.details == {"document_id": document["id"], "file_name": "slides.pdf", "size_bytes": 15}
    assert entry.actor_hash == actor_hash(user.id)


@pytest.mark.parametrize("file_name, file_type", [("notes.txt", "txt"), ("Paper.DOCX", "docx"), ("deck.pptx", "pptx")])
def test_every_fr03_format_is_accepted(client, project_id, file_name, file_type):
    response = upload(client, project_id, (file_name, b"content", "application/octet-stream"))

    assert response.status_code == 201
    assert response.json()["file_type"] == file_type


@pytest.mark.parametrize("file, message", [
    (("video.mp4", b"x", "video/mp4"), "extension 'mp4' is not supported"),
    (("README", b"x", "text/plain"), "extension '' is not supported"),
    (("empty.pdf", b"", "application/pdf"), "the file is empty"),
    (("x" * 252 + ".pdf", b"x", "application/pdf"), "file name must have between 1 and 255 characters"),
])
def test_invalid_documents_are_rejected(client, project_id, object_storage, db, file, message):
    response = upload(client, project_id, file)

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert object_storage.objects == {}
    assert document_count(db) == 0


def test_a_document_over_the_size_limit_is_rejected(client, project_id, small_limits):
    response = upload(client, project_id, ("big.pdf", b"x" * 11, "application/pdf"))

    assert response.status_code == 422
    assert "exceeds the upload limit of 10 bytes" in response.json()["detail"]


def test_a_project_has_a_limited_number_of_documents(client, project_id, small_limits):
    assert upload(client, project_id, ("a.pdf", b"a", "application/pdf")).status_code == 201
    assert upload(client, project_id, ("b.pdf", b"b", "application/pdf")).status_code == 201

    response = upload(client, project_id, ("c.pdf", b"c", "application/pdf"))

    assert response.status_code == 422
    assert "at most 2 supporting documents" in response.json()["detail"]


def test_a_deleted_document_removes_its_file(client, project_id, object_storage, db):
    document_id = upload(client, project_id).json()["id"]

    assert client.delete(f"{documents_url(project_id)}/{document_id}").status_code == 204

    assert client.get(documents_url(project_id)).json() == []
    assert object_storage.objects == {}
    actions = db.scalars(select(AuditLog.action)).all()
    assert AuditAction.DOCUMENT_REMOVED in actions


def test_a_storage_failure_on_upload_keeps_nothing(client, project_id, db):
    app.dependency_overrides[get_object_storage] = lambda: UnavailableObjectStorage()

    assert upload(client, project_id).status_code == 503
    assert document_count(db) == 0


def test_a_storage_failure_keeps_the_document_so_the_deletion_can_be_repeated(client, project_id, object_storage):
    url = f"{documents_url(project_id)}/{upload(client, project_id).json()['id']}"
    app.dependency_overrides[get_object_storage] = lambda: UnavailableObjectStorage()

    assert client.delete(url).status_code == 503

    app.dependency_overrides[get_object_storage] = lambda: object_storage
    assert len(client.get(documents_url(project_id)).json()) == 1
    assert client.delete(url).status_code == 204


def test_a_document_of_another_project_is_not_found(client, project_id):
    other_project = client.post("/projects", json=PROJECT_BODY).json()["id"]
    document_id = upload(client, other_project).json()["id"]

    assert client.delete(f"{documents_url(project_id)}/{document_id}").status_code == 404


def test_documents_of_an_unknown_project_are_not_found(client):
    unknown = uuid.uuid4()

    assert client.get(documents_url(unknown)).status_code == 404
    assert upload(client, unknown).status_code == 404


def test_an_unknown_or_invalid_document_id_is_reported(client, project_id):
    assert client.delete(f"{documents_url(project_id)}/{uuid.uuid4()}").status_code == 404
    assert client.delete(f"{documents_url(project_id)}/not-a-uuid").status_code == 422