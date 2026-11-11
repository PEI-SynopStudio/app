import asyncio
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import JobStatusEnum, JobTypeEnum, LicenseType
from app.database.session import get_session_factory
from app.main import app
from app.schemas.job import IngestionParams, JobStatusResponseSchema
from app.schemas.project import ProjectCreate
from app.services.projects.projects import create_project
from app.services.workflow.jobs import create_ingestion_job, queue_job
from app.services.workflow.progress_hub import JobProgressHub, get_progress_hub

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"


@pytest.fixture
def hub():
    return JobProgressHub()


@pytest.fixture
def client(session_factory, hub):
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_progress_hub] = lambda: hub
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_project(db):
    return create_project(db, ProjectCreate(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=True,
        authorship_confirmed=True,
    )).id


def update_for(project_id, progress=10.0):
    now = datetime.now(timezone.utc)
    return JobStatusResponseSchema(
        job_id=uuid.uuid4(),
        project_id=project_id,
        job_type=JobTypeEnum.INGESTION,
        status=JobStatusEnum.PROCESSING,
        progress=progress,
        created_at=now,
        updated_at=now,
    )


def publish(client, hub, update):
    """Publish on the event loop of the running application, as the consumer does."""
    client.portal.call(hub.publish, update)


def test_a_new_connection_receives_the_current_state(client, db):
    project_id = make_project(db)
    job = queue_job(db, create_ingestion_job(db, str(project_id), IngestionParams(source_url=SAMPLE_URL), SAMPLE_URL))

    with client.websocket_connect(f"/projects/{project_id}/progress") as websocket:
        state = websocket.receive_json()

    assert (state["job_id"], state["status"]) == (str(job.id), "queued")


def test_updates_are_sent_while_connected(client, db, hub):
    project_id = make_project(db)

    with client.websocket_connect(f"/projects/{project_id}/progress") as websocket:
        publish(client, hub, update_for(project_id, 25.0))
        assert websocket.receive_json()["progress"] == 25.0
        publish(client, hub, update_for(project_id, 60.0))
        assert websocket.receive_json()["progress"] == 60.0


def test_a_connection_only_receives_its_own_project(client, db, hub):
    project_id, other_project_id = make_project(db), make_project(db)

    with client.websocket_connect(f"/projects/{project_id}/progress") as websocket:
        publish(client, hub, update_for(other_project_id, 99.0))
        publish(client, hub, update_for(project_id, 25.0))

        assert websocket.receive_json()["project_id"] == str(project_id)


def test_messages_from_the_client_are_ignored(client, db, hub):
    project_id = make_project(db)

    with client.websocket_connect(f"/projects/{project_id}/progress") as websocket:
        websocket.send_text("hello")
        websocket.send_bytes(b"hello")
        publish(client, hub, update_for(project_id, 25.0))

        assert websocket.receive_json()["progress"] == 25.0


@pytest.mark.parametrize("project_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_unknown_project_is_closed_with_a_clear_code(client, project_id):
    with client.websocket_connect(f"/projects/{project_id}/progress") as websocket:
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    assert closed.value.code == 4404


def test_disconnecting_removes_the_watcher(client, db, hub):
    project_id = make_project(db)

    with client.websocket_connect(f"/projects/{project_id}/progress") as websocket:
        publish(client, hub, update_for(project_id))
        websocket.receive_json()

    client.portal.call(asyncio.sleep, 0.05)
    assert hub._watchers == {}


def test_hub_keeps_only_the_newest_update_for_a_slow_client(hub):
    project_id = uuid.uuid4()

    with hub.watch(project_id) as updates:
        hub.publish(update_for(project_id, 10.0))
        hub.publish(update_for(project_id, 20.0))
        hub.publish(update_for(project_id, 30.0))

        assert updates.qsize() == 1
        assert updates.get_nowait().progress == 30.0


def test_publishing_without_watchers_does_nothing(hub):
    hub.publish(update_for(uuid.uuid4()))

    assert hub._watchers == {}
