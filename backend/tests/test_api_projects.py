import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import AuditAction, JobTypeEnum, MediaAssetStatus, SourceType
from app.database.base import utc_now
from app.database.models import AuditLog, Clip, Job, MediaAsset, Project, ProjectDocument
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


def new_project(client, title="Debate"):
    return client.post("/projects", json={**PROJECT_BODY, "title": title}).json()["id"]


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


# --- Project settings, library and changes ---

SETTINGS = {"description": "Pick the moments about AI.", "aspect_ratio": "16:9", "language": "en", "caption_style": None}
CLIP_BODY = {"title": "Final advice", "scenes": [{"start": 3790, "end": 3818}]}


def titles(response):
    return [item["title"] for item in response.json()["items"]]


def age(db, project_id, days):
    """Make a project look as if it was last changed `days` ago."""
    project = db.get(Project, uuid.UUID(project_id))
    project.updated_at = utc_now() - timedelta(days=days)
    db.commit()


def updates(db):
    return db.scalars(select(AuditLog).where(AuditLog.action == AuditAction.PROJECT_UPDATED)).all()


def test_a_new_project_gets_the_default_settings(client):
    project = client.post("/projects", json=PROJECT_BODY).json()

    assert {key: project[key] for key in SETTINGS} == {
        "description": None, "aspect_ratio": "9:16", "language": "pt-PT", "caption_style": "classic"
    }
    assert project["clips"] == []
    assert project["documents"] == []


def test_a_project_keeps_its_settings(client):
    created = client.post("/projects", json={**PROJECT_BODY, **SETTINGS})

    assert created.status_code == 201
    stored = client.get(f"/projects/{created.json()['id']}").json()
    assert {key: stored[key] for key in SETTINGS} == SETTINGS


@pytest.mark.parametrize("field, value", [
    ("title", "   "),
    ("description", "x" * 2001),
    ("aspect_ratio", "21:9"),
    ("language", "fr"),
    ("caption_style", "comic"),
])
def test_invalid_settings_are_rejected(client, field, value):
    assert client.post("/projects", json={**PROJECT_BODY, field: value}).status_code == 422


def test_a_blank_description_means_no_prompt(client):
    assert client.post("/projects", json={**PROJECT_BODY, "description": "   "}).json()["description"] is None


def test_the_library_lists_the_most_recently_changed_project_first(client, db):
    lecture, debate, podcast = new_project(client, "Lecture"), new_project(client, "Debate"), new_project(client, "Podcast")
    age(db, lecture, days=3)
    age(db, debate, days=1)
    age(db, podcast, days=2)

    page = client.get("/projects").json()

    assert [item["id"] for item in page["items"]] == [debate, podcast, lecture]
    assert (page["total"], page["limit"], page["offset"]) == (3, 50, 0)


def test_the_library_is_paginated(client, db):
    ids = [new_project(client, f"Project {number}") for number in range(3)]
    for days, project_id in enumerate(ids):
        age(db, project_id, days)

    page = client.get("/projects", params={"limit": 2, "offset": 1}).json()

    assert [item["id"] for item in page["items"]] == ids[1:]
    assert page["total"] == 3


def test_the_library_searches_by_title_and_filters_by_status(client):
    new_project(client, "Open Lecture — Distributed Systems")
    new_project(client, "Tech Podcast #31")

    assert titles(client.get("/projects", params={"q": "LECTURE"})) == ["Open Lecture — Distributed Systems"]
    assert titles(client.get("/projects", params={"q": "%"})) == []  # searched literally, not as a wildcard
    assert client.get("/projects", params={"status": "ingested"}).json()["total"] == 0
    assert client.get("/projects", params={"status": "draft"}).json()["total"] == 2


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "archived"}])
def test_invalid_library_parameters_are_rejected(client, params):
    assert client.get("/projects", params=params).status_code == 422


def test_the_library_counts_the_clips_of_each_project(client):
    project_id = new_project(client)
    client.post(f"/projects/{project_id}/clips", json=CLIP_BODY)
    client.post(f"/projects/{project_id}/clips", json=CLIP_BODY)
    new_project(client, "Without clips")

    counts = {item["title"]: item["clip_count"] for item in client.get("/projects").json()["items"]}

    assert counts == {"Debate": 2, "Without clips": 0}


def test_project_settings_can_be_changed_and_the_change_is_audited(client, db):
    project_id = new_project(client)

    response = client.patch(
        f"/projects/{project_id}", json={"title": "Debate — final", "aspect_ratio": "1:1", "caption_style": None}
    )

    assert response.status_code == 200
    project = response.json()
    assert (project["title"], project["aspect_ratio"], project["caption_style"]) == ("Debate — final", "1:1", None)
    assert project["language"] == "pt-PT"  # omitted fields keep their value
    [entry] = updates(db)
    assert entry.details == {"changes": {"title": "Debate — final", "aspect_ratio": "1:1", "caption_style": None}}


def test_a_change_to_the_same_value_records_nothing(client, db):
    project_id = new_project(client)

    assert client.patch(f"/projects/{project_id}", json={"aspect_ratio": "9:16"}).status_code == 200
    assert updates(db) == []


@pytest.mark.parametrize("body", [
    {"title": None},
    {"title": ""},
    {"aspect_ratio": None},
    {"language": None},
    {"author": "Someone else"},  # the FR01 metadata is not editable here
    {"licence_confirmed": False},
])
def test_invalid_project_changes_are_rejected(client, body):
    project_id = new_project(client)

    assert client.patch(f"/projects/{project_id}", json=body).status_code == 422


def test_changing_an_unknown_project_is_not_found(client):
    assert client.patch(f"/projects/{uuid.uuid4()}", json={"title": "Debate"}).status_code == 404


def test_deleting_a_project_removes_its_clips_and_documents(client, db, object_storage):
    project_id = new_project(client)
    client.post(f"/projects/{project_id}/clips", json=CLIP_BODY)
    client.post(f"/projects/{project_id}/documents", files={"file": ("slides.pdf", b"%PDF-1.7", "application/pdf")})

    assert client.delete(f"/projects/{project_id}").status_code == 204

    assert db.scalar(select(func.count()).select_from(Clip)) == 0
    assert db.scalar(select(func.count()).select_from(ProjectDocument)) == 0
    assert object_storage.objects == {}
