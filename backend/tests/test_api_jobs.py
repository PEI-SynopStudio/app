import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.core.config import JobStatusEnum, LicenseType
from app.database.models import Job
from app.main import app
from app.schemas.job import IngestionParams
from app.schemas.project import ProjectCreate
from app.services.projects.projects import create_project
from app.services.workflow.jobs import create_ingestion_job, queue_job

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"


@pytest.fixture
def client(db_override):
    yield TestClient(app)
    app.dependency_overrides.clear()


def queued_job(db):
    project = create_project(db, ProjectCreate(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=True,
        authorship_confirmed=True,
    ))
    params = IngestionParams(source_url=SAMPLE_URL)
    return queue_job(db, create_ingestion_job(db, str(project.id), params, SAMPLE_URL))


def test_job_can_be_read(client, db):
    job = queued_job(db)

    response = client.get(f"/projects/{job.project_id}/jobs/{job.id}")

    assert response.status_code == 200
    assert (response.json()["job_id"], response.json()["status"]) == (str(job.id), "queued")


def test_unknown_job_is_not_found(client, db):
    assert client.get(f"/projects/{queued_job(db).project_id}/jobs/{uuid.uuid4()}").status_code == 404


def test_job_of_another_project_is_not_found(client, db):
    assert client.get(f"/projects/{uuid.uuid4()}/jobs/{queued_job(db).id}").status_code == 404


def test_invalid_job_id_is_rejected(client, db):
    assert client.get(f"/projects/{queued_job(db).project_id}/jobs/not-a-uuid").status_code == 422


def test_restarting_the_api_leaves_the_jobs_alone(session_factory, db, monkeypatch):
    """The jobs run in the workers, which do not restart with the API."""
    job = queued_job(db)
    monkeypatch.setattr(main_module, "get_session_factory", lambda: session_factory)

    with TestClient(app):
        pass

    db.expire_all()
    assert db.get(Job, job.id).status == JobStatusEnum.QUEUED
