import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import AuditAction, JobErrorCodeEnum
from app.core.exceptions import JobDispatchError
from app.database.models import AuditLog, Project
from app.main import app
from app.schemas.job import TranscriptionParams
from app.services.auth.auth import actor_hash
from app.services.workflow.dispatcher import JobDispatcher
from app.services.workflow.jobs import apply_job_event, create_transcription_job, fail_job, queue_job
from app.services.workflow.rabbitmq import get_dispatcher
from conftest import add_user, sign_in
from test_submission import dispatcher, finished_asset, make_project, storage  # noqa: F401
from test_transcription_results import completed, transcription  # noqa: F401


class UnreachableBroker(JobDispatcher):
    def dispatch(self, request):
        raise JobDispatchError("The job could not be queued; please try again.")


def own(db, project_id, user):
    """Give the project to the signed-in test user, so the API lets the client reach it."""
    db.get(Project, uuid.UUID(project_id)).owner_id = user.id
    db.commit()
    return project_id


@pytest.fixture
def client(db_override, dispatcher, session_factory, user):
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    yield sign_in(TestClient(app), session_factory, user)
    app.dependency_overrides.clear()


@pytest.fixture
def failed(db, storage, user):
    project_id = own(db, make_project(db), user)
    asset, _ = finished_asset(db, storage, project_id)
    job = queue_job(db, create_transcription_job(db, project_id, TranscriptionParams(media_id=asset.id), asset.id))
    fail_job(db, job, JobErrorCodeEnum.MODEL_UNAVAILABLE, "no weights")
    return project_id, asset


@pytest.fixture
def stored(db, transcription, user):
    job, object_storage = transcription
    apply_job_event(db, completed(job), lambda: object_storage)
    return own(db, str(job.project_id), user)


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


def test_a_project_without_transcript_is_not_found(client, db, user):
    project_id = own(db, make_project(db), user)

    response = client.get(f"/projects/{project_id}/transcript")

    assert response.status_code == 404
    assert "no transcript yet" in response.json()["detail"]


def test_an_unknown_project_is_not_found(client):
    assert client.get(f"/projects/{uuid.uuid4()}/transcript").status_code == 404


def test_an_invalid_project_id_is_rejected(client):
    assert client.get("/projects/not-a-uuid/transcript").status_code == 422


def test_a_failed_transcription_can_be_started_again(client, dispatcher, failed):
    project_id, asset = failed

    response = client.post(f"/projects/{project_id}/transcription")

    assert response.status_code == 202
    assert (response.json()["job_type"], response.json()["status"]) == ("transcription", "queued")
    [request] = dispatcher.requests
    assert (request.parameters.media_id, request.audio_key) == (asset.id, "audio/audio.wav")


def test_a_second_request_while_one_is_running_is_conflict(client, failed):
    project_id, _ = failed
    client.post(f"/projects/{project_id}/transcription")

    response = client.post(f"/projects/{project_id}/transcription")

    assert response.status_code == 409


def test_a_video_already_transcribed_is_conflict(client, stored):
    response = client.post(f"/projects/{stored}/transcription")

    assert response.status_code == 409
    assert "already transcribed" in response.json()["detail"]


def test_a_project_without_licence_is_forbidden(client, db, storage, user):
    project_id = own(db, make_project(db, licence=False), user)
    finished_asset(db, storage, project_id)

    assert client.post(f"/projects/{project_id}/transcription").status_code == 403


def test_a_project_without_a_finished_video_is_not_found(client, db, user):
    project_id = own(db, make_project(db), user)

    assert client.post(f"/projects/{project_id}/transcription").status_code == 404


def test_an_unreachable_broker_answers_503(client, failed):
    project_id, _ = failed
    app.dependency_overrides[get_dispatcher] = UnreachableBroker

    assert client.post(f"/projects/{project_id}/transcription").status_code == 503


def test_the_transcript_needs_a_signed_in_user(client, stored):
    client.cookies.clear()

    assert client.get(f"/projects/{stored}/transcript").status_code == 401
    assert client.post(f"/projects/{stored}/transcription").status_code == 401


def test_another_users_project_is_not_found(client, db, session_factory, stored):
    other = add_user(session_factory, subject="subject-2", email="other@example.com", name="Other")
    own(db, stored, other)

    assert client.get(f"/projects/{stored}/transcript").status_code == 404
    assert client.post(f"/projects/{stored}/transcription").status_code == 404


def test_the_request_is_recorded_with_the_user(client, db, user, failed):
    project_id, _ = failed

    client.post(f"/projects/{project_id}/transcription")

    query = select(AuditLog).where(AuditLog.action == AuditAction.TRANSCRIPTION_REQUESTED)
    entry = db.scalars(query.order_by(AuditLog.created_at.desc())).first()
    assert entry.actor_hash == actor_hash(user.id)
