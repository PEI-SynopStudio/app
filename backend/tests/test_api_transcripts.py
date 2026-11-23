import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.workflow.jobs import apply_job_event
from test_submission import finished_asset, make_project, storage  # noqa: F401
from test_transcription_results import completed, transcription  # noqa: F401


@pytest.fixture
def client(db_override):
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def stored(db, transcription):
    job, object_storage = transcription
    apply_job_event(db, completed(job), lambda: object_storage)
    return str(job.project_id)


def test_the_whole_transcript_is_returned_with_its_models(client, stored):
    response = client.get(f"/projects/{stored}/transcript")

    assert response.status_code == 200
    body = response.json()
    assert (body["ai_generated"], body["language"], body["model_revision"], body["word_count"]) == (True, "pt", "a" * 40, 4)
    assert [segment["text"] for segment in body["segments"]] == ["Bom dia.", "Em 2024."]
    assert [(word["text"], word["aligned"]) for word in body["segments"][1]["words"]] == [("Em", True), ("2024.", False)]


@pytest.mark.parametrize(
    "query, texts",
    [
        ("start=1.8", ["Em 2024."]),
        ("end=1.8", ["Bom dia."]),
        ("start=1.5&end=2.1", ["Bom dia.", "Em 2024."]),
        ("start=3", []),
    ],
)
def test_a_time_range_returns_the_segments_that_overlap_it(client, stored, query, texts):
    response = client.get(f"/projects/{stored}/transcript?{query}")

    assert [segment["text"] for segment in response.json()["segments"]] == texts


@pytest.mark.parametrize("query", ["start=2&end=1", "start=2&end=2", "start=-1"])
def test_an_invalid_range_is_rejected(client, stored, query):
    assert client.get(f"/projects/{stored}/transcript?{query}").status_code == 422


def test_a_project_without_transcript_is_not_found(client, db):
    project_id = make_project(db)

    response = client.get(f"/projects/{project_id}/transcript")

    assert response.status_code == 404
    assert "no transcript yet" in response.json()["detail"]


def test_an_unknown_project_is_not_found(client):
    assert client.get(f"/projects/{uuid.uuid4()}/transcript").status_code == 404


def test_an_invalid_project_id_is_rejected(client):
    assert client.get("/projects/not-a-uuid/transcript").status_code == 422
