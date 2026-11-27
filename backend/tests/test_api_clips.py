import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import AuditAction
from app.database.models import AuditLog
from app.main import app
from test_api_projects import PROJECT_BODY, age
from app.services.auth.auth import actor_hash
from conftest import sign_in

CLIP_BODY = {
    "title": "The Question That Changed Everything",
    "scenes": [{"start": 312, "end": 326}, {"start": 340, "end": 356.5}],
}
SCENES = [{"start": 312.0, "end": 326.0}, {"start": 340.0, "end": 356.5}]


@pytest.fixture
def client(db_override, session_factory, user):
    yield sign_in(TestClient(app), session_factory, user)
    app.dependency_overrides.clear()


@pytest.fixture
def project_id(client):
    return client.post("/projects", json=PROJECT_BODY).json()["id"]


def clips_url(project_id):
    return f"/projects/{project_id}/clips"


def new_clip(client, project_id, **changes):
    return client.post(clips_url(project_id), json={**CLIP_BODY, **changes}).json()


def audit(db, action):
    return db.scalars(select(AuditLog).where(AuditLog.action == action)).all()


def test_a_clip_keeps_its_scenes_in_the_order_they_play(client, project_id):
    response = client.post(clips_url(project_id), json=CLIP_BODY)

    assert response.status_code == 201
    clip = response.json()
    assert clip["title"] == CLIP_BODY["title"]
    assert clip["scenes"] == SCENES
    assert clip["duration_seconds"] == 30.5
    assert clip["subtitle_language"] is None  # the language spoken in the video
    assert clip["project_id"] == project_id
    assert client.get(f"{clips_url(project_id)}/{clip['id']}").json() == clip


def test_creating_a_clip_is_audited(client, project_id, db, user):
    clip = new_clip(client, project_id)

    [entry] = audit(db, AuditAction.CLIP_CREATED)
    assert entry.details == {"clip_id": clip["id"], "title": CLIP_BODY["title"], "scenes": SCENES, "subtitle_language": None}
    assert entry.actor_hash == actor_hash(user.id)

def test_new_clips_go_to_the_end_of_the_project(client, project_id):
    ids = [new_clip(client, project_id, title=f"Clip {number}")["id"] for number in range(3)]

    listed = client.get(clips_url(project_id)).json()

    assert [clip["id"] for clip in listed] == ids
    assert [clip["position"] for clip in listed] == [1, 2, 3]
    assert [clip["id"] for clip in client.get(f"/projects/{project_id}").json()["clips"]] == ids


def test_a_clip_can_have_translated_subtitles(client, project_id):
    assert new_clip(client, project_id, subtitle_language="en")["subtitle_language"] == "en"


@pytest.mark.parametrize("changes", [
    {"title": "   "},
    {"title": "x" * 301},
    {"scenes": []},
    {"scenes": [{"start": 10, "end": 10}]},
    {"scenes": [{"start": 20, "end": 10}]},
    {"scenes": [{"start": -1, "end": 10}]},
    {"scenes": [{"start": 0, "end": 1}] * 51},
    {"scenes": [{"start": 0}]},
    {"subtitle_language": "fr"},
])
def test_invalid_clips_are_rejected(client, project_id, changes):
    assert client.post(clips_url(project_id), json={**CLIP_BODY, **changes}).status_code == 422


def test_a_clip_needs_a_title(client, project_id):
    assert client.post(clips_url(project_id), json={"scenes": CLIP_BODY["scenes"]}).status_code == 422


def test_a_clip_can_be_edited_and_the_change_is_audited(client, project_id, db):
    clip = new_clip(client, project_id)
    changes = {"title": "Final advice", "scenes": [{"start": 3790.0, "end": 3818.0}], "subtitle_language": "es"}

    response = client.patch(f"{clips_url(project_id)}/{clip['id']}", json=changes)

    assert response.status_code == 200
    edited = response.json()
    assert {key: edited[key] for key in changes} == changes
    assert edited["duration_seconds"] == 28.0
    [entry] = audit(db, AuditAction.CLIP_UPDATED)
    assert entry.details == {"clip_id": clip["id"], "changes": changes}


def test_omitted_fields_keep_their_value(client, project_id):
    clip = new_clip(client, project_id, subtitle_language="en")

    edited = client.patch(f"{clips_url(project_id)}/{clip['id']}", json={"title": "Renamed"}).json()

    assert edited["title"] == "Renamed"
    assert edited["scenes"] == SCENES
    assert edited["subtitle_language"] == "en"


def test_null_subtitle_language_goes_back_to_the_spoken_language(client, project_id):
    clip = new_clip(client, project_id, subtitle_language="en")

    edited = client.patch(f"{clips_url(project_id)}/{clip['id']}", json={"subtitle_language": None}).json()

    assert edited["subtitle_language"] is None


def test_a_change_to_the_same_value_records_nothing(client, project_id, db):
    clip = new_clip(client, project_id)

    assert client.patch(f"{clips_url(project_id)}/{clip['id']}", json={"scenes": SCENES}).status_code == 200
    assert audit(db, AuditAction.CLIP_UPDATED) == []


@pytest.mark.parametrize("body", [
    {"title": None},
    {"title": ""},
    {"scenes": None},
    {"scenes": []},
    {"position": 3},
])
def test_invalid_clip_changes_are_rejected(client, project_id, body):
    clip = new_clip(client, project_id)

    assert client.patch(f"{clips_url(project_id)}/{clip['id']}", json=body).status_code == 422


def test_a_deleted_clip_is_gone_but_stays_in_the_audit_log(client, project_id, db):
    clip = new_clip(client, project_id)
    url = f"{clips_url(project_id)}/{clip['id']}"

    assert client.delete(url).status_code == 204

    assert client.get(url).status_code == 404
    assert client.get(clips_url(project_id)).json() == []
    [entry] = audit(db, AuditAction.CLIP_DELETED)
    assert entry.details == {"clip_id": clip["id"], "title": CLIP_BODY["title"], "scenes": SCENES}


def test_a_clip_of_another_project_is_not_found(client, project_id):
    other_project = client.post("/projects", json=PROJECT_BODY).json()["id"]
    url = f"{clips_url(project_id)}/{new_clip(client, other_project)['id']}"

    assert client.get(url).status_code == 404
    assert client.patch(url, json={"title": "Renamed"}).status_code == 404
    assert client.delete(url).status_code == 404


def test_clips_of_an_unknown_project_are_not_found(client):
    url = clips_url(uuid.uuid4())

    assert client.get(url).status_code == 404
    assert client.post(url, json=CLIP_BODY).status_code == 404


def test_an_unknown_or_invalid_clip_id_is_reported(client, project_id):
    assert client.get(f"{clips_url(project_id)}/{uuid.uuid4()}").status_code == 404
    assert client.get(f"{clips_url(project_id)}/not-a-uuid").status_code == 422


def test_a_clip_change_moves_its_project_to_the_top_of_the_library(client, project_id, db):
    other_project = client.post("/projects", json={**PROJECT_BODY, "title": "Other"}).json()["id"]
    age(db, project_id, days=1)

    new_clip(client, project_id)

    assert [item["id"] for item in client.get("/projects").json()["items"]] == [project_id, other_project]