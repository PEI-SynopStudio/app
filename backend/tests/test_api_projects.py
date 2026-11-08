import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

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
def client(db_override):
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
