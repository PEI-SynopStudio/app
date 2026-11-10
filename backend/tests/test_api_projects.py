import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import AuditAction, JobTypeEnum, MediaAssetStatus, SourceType
from app.database.models import AuditLog, Job, MediaAsset
from app.main import app
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import ObjectStorageError, get_object_storage
from in_memory_object_storage import InMemoryObjectStorage, UnavailableObjectStorage

PROJECT_BODY = {
    "title": "Debate",
    "author": "University of Aveiro",
    "speakers": ["Ana", "Rui"],
    "recording_date": "2026-10-01",
    "license_type": "creative_commons",
    "copyright_notice": "CC BY 4.0",
    "licence_confirmed": True,
    "authorship_confirmed": True,
}


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def object_storage():
    return InMemoryObjectStorage()


@pytest.fixture
def client(db_override, storage, object_storage):
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_object_storage] = lambda: object_storage
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_project_keeps_the_fr01_metadata(client):
    created = client.post("/projects", json=PROJECT_BODY)

    assert created.status_code == 201
    stored = client.get(f"/projects/{created.json()['id']}").json()
    assert {key: stored[key] for key in PROJECT_BODY} == PROJECT_BODY
    assert stored["status"] == "draft"


@pytest.mark.parametrize("field", list(PROJECT_BODY))
def test_every_fr01_field_is_mandatory(client, field):
    body = {key: value for key, value in PROJECT_BODY.items() if key != field}

    assert client.post("/projects", json=body).status_code == 422


@pytest.mark.parametrize("field, value", [
    ("title", ""),
    ("author", ""),
    ("speakers", []),
    ("speakers", [""]),
    ("recording_date", "yesterday"),
    ("license_type", "all_rights_reserved"),
    ("copyright_notice", ""),
])
def test_invalid_fr01_values_are_rejected(client, field, value):
    assert client.post("/projects", json={**PROJECT_BODY, field: value}).status_code == 422


def test_unknown_project_is_not_found(client):
    assert client.get(f"/projects/{uuid.uuid4()}").status_code == 404


def test_invalid_project_id_is_rejected(client):
    assert client.get("/projects/not-a-uuid").status_code == 422


def new_project(client):
    return client.post("/projects", json=PROJECT_BODY).json()["id"]


def test_deleting_a_project_removes_its_data_and_keeps_the_audit_log(client, storage, db):
    project_id = new_project(client)
    project_uuid = uuid.UUID(project_id)
    storage.path(project_id, "source", "video.mp4").write_bytes(b"x")
    db.add(MediaAsset(
        project_id=project_uuid, source_type=SourceType.UPLOAD, file_name="video.mp4", status=MediaAssetStatus.READY
    ))
    db.commit()

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 204
    assert client.get(f"/projects/{project_id}").status_code == 404
    assert not storage.project_dir(project_id).exists()
    assert db.scalar(select(func.count()).select_from(MediaAsset)) == 0
    actions = db.scalars(select(AuditLog.action).where(AuditLog.project_id == project_uuid)).all()
    assert {AuditAction.LICENCE_CONFIRMED, AuditAction.PROJECT_DELETED} <= set(actions)


def test_deleting_a_project_removes_its_objects(client, object_storage):
    project_id = new_project(client)
    other_project = str(uuid.uuid4())
    object_storage.objects[(project_id, "proxy/proxy.mp4")] = b"x"
    object_storage.objects[(other_project, "proxy/proxy.mp4")] = b"y"

    assert client.delete(f"/projects/{project_id}").status_code == 204

    assert list(object_storage.objects) == [(other_project, "proxy/proxy.mp4")]


def test_a_storage_failure_keeps_the_project_so_the_deletion_can_be_repeated(client, storage, object_storage, db):
    project_id = new_project(client)
    local_file = storage.path(project_id, "source", "video.mp4")
    local_file.write_bytes(b"x")
    app.dependency_overrides[get_object_storage] = lambda: UnavailableObjectStorage()

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 503
    assert response.json()["detail"] == "The storage service is unavailable; please try again."
    assert client.get(f"/projects/{project_id}").status_code == 200
    assert local_file.exists()
    actions = db.scalars(select(AuditLog.action).where(AuditLog.project_id == uuid.UUID(project_id))).all()
    assert AuditAction.PROJECT_DELETED not in actions

    app.dependency_overrides[get_object_storage] = lambda: object_storage
    assert client.delete(f"/projects/{project_id}").status_code == 204
    assert client.get(f"/projects/{project_id}").status_code == 404


def test_a_storage_that_cannot_be_opened_is_reported(client):
    project_id = new_project(client)

    def unavailable():
        raise ObjectStorageError("storage down")

    app.dependency_overrides[get_object_storage] = unavailable

    assert client.delete(f"/projects/{project_id}").status_code == 503
    assert client.get(f"/projects/{project_id}").status_code == 200


def test_a_project_with_an_active_ingestion_cannot_be_deleted(client, db):
    project_id = new_project(client)
    db.add(Job(project_id=uuid.UUID(project_id), job_type=JobTypeEnum.INGESTION, parameters={}))
    db.commit()

    assert client.delete(f"/projects/{project_id}").status_code == 409
    assert client.get(f"/projects/{project_id}").status_code == 200


def test_deleting_an_unknown_project_is_not_found(client):
    assert client.delete(f"/projects/{uuid.uuid4()}").status_code == 404
