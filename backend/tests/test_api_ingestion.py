import shutil
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import JobDispatchError
from app.main import app
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import get_object_storage
from app.services.video.sources import RemoteVideoInfo
from app.services.workflow import ingestion_pipeline
from app.services.workflow.dispatcher import JobDispatcher
from app.services.workflow.rabbitmq import get_dispatcher
from in_memory_object_storage import InMemoryObjectStorage
from in_process_dispatcher import InProcessDispatcher

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
JOIN_TIMEOUT_SECONDS = 60
PROJECT_BODY = {
    "title": "Debate",
    "author": "University of Aveiro",
    "speakers": ["Ana"],
    "recording_date": "2026-10-01",
    "license_type": "creative_commons",
    "copyright_notice": "CC BY 4.0",
    "authorship_confirmed": True,
}


class RecordingDispatcher(JobDispatcher):
    """Accepts jobs without running them, so endpoint tests stay fast and offline."""

    def __init__(self):
        self.requests = []

    def dispatch(self, request):
        self.requests.append(request)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def dispatcher():
    return RecordingDispatcher()


@pytest.fixture
def client(storage, dispatcher, db_override):
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_object_storage] = InMemoryObjectStorage
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def live(storage, db_override, session_factory):
    """Client wired to the in-process stand-in; yields (client, dispatcher, published events)."""
    events = []
    object_storage = InMemoryObjectStorage()
    dispatcher = InProcessDispatcher(storage, object_storage, session_factory, publish_event=events.append)
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_object_storage] = lambda: object_storage
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    yield TestClient(app), dispatcher, events
    dispatcher.join(JOIN_TIMEOUT_SECONDS)
    app.dependency_overrides.clear()


@pytest.fixture
def fake_youtube(monkeypatch):
    """Replace the yt-dlp probe and download in the pipeline; the 'download' copies the given sample."""
    def install(sample):
        monkeypatch.setattr(
            ingestion_pipeline, "probe_remote_video", lambda url: RemoteVideoInfo(url=url, duration_seconds=600)
        )
        monkeypatch.setattr(
            ingestion_pipeline, "download_youtube_video",
            lambda url, output_path, start_time, end_time, on_progress: shutil.copy(sample, output_path),
        )

    return install


class UnreachableBrokerDispatcher(JobDispatcher):
    def dispatch(self, request):
        raise JobDispatchError("The job could not be queued; please try again.")


def new_project(client, licence=True):
    response = client.post("/projects", json={**PROJECT_BODY, "licence_confirmed": licence})
    return response.json()["id"]


def test_url_ingestion_is_accepted_and_queued(client, dispatcher):
    project_id = new_project(client)

    response = client.post(
        f"/projects/{project_id}/ingestions/url",
        json={"url": SAMPLE_URL, "start_time": "00:01:07", "end_time": "00:01:27"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    params = dispatcher.requests[0].parameters
    assert (str(params.source_url), params.time_start, params.time_end) == (SAMPLE_URL, "00:01:07", "00:01:27")


@pytest.mark.parametrize("body, message", [
    ({"url": "https://example.com/video.mp4"}, "domain not allowed"),
    ({"url": "not a url"}, "Invalid URL"),
    ({"url": SAMPLE_URL, "start_time": "00:02:00", "end_time": "00:01:00"}, "Invalid time range"),
])
def test_invalid_url_request_is_rejected(client, dispatcher, body, message):
    project_id = new_project(client)

    response = client.post(f"/projects/{project_id}/ingestions/url", json=body)

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert dispatcher.requests == []


def test_url_ingestion_accepts_an_open_ended_time_range(client, dispatcher):
    project_id = new_project(client)

    response = client.post(
        f"/projects/{project_id}/ingestions/url", json={"url": SAMPLE_URL, "start_time": "00:01:00"}
    )

    assert response.status_code == 202
    params = dispatcher.requests[0].parameters
    assert (params.time_start, params.time_end) == ("00:01:00", None)


def test_url_ingestion_without_licence_is_forbidden(live):
    client, _, _ = live
    project_id = new_project(client, licence=False)

    response = client.post(f"/projects/{project_id}/ingestions/url", json={"url": SAMPLE_URL})

    assert response.status_code == 403
    assert "licence" in response.json()["detail"]


def test_url_ingestion_for_unknown_project_is_not_found(live):
    client, _, _ = live

    response = client.post(f"/projects/{uuid.uuid4()}/ingestions/url", json={"url": SAMPLE_URL})

    assert response.status_code == 404


def test_url_ingestion_with_invalid_project_id_is_rejected(client):
    response = client.post("/projects/not-a-uuid/ingestions/url", json={"url": SAMPLE_URL})

    assert response.status_code == 422


def test_second_ingestion_while_running_is_conflict(client):
    project_id = new_project(client)
    client.post(f"/projects/{project_id}/ingestions/url", json={"url": SAMPLE_URL})

    response = client.post(f"/projects/{project_id}/ingestions/url", json={"url": SAMPLE_URL})

    assert response.status_code == 409


def test_status_before_any_ingestion_is_not_found(client):
    response = client.get(f"/projects/{new_project(client)}/ingestion")

    assert response.status_code == 404
    assert "No ingestion has been started" in response.json()["detail"]


def test_status_of_unknown_project_is_not_found(client):
    assert client.get(f"/projects/{uuid.uuid4()}/ingestion").status_code == 404


def test_url_ingestion_end_to_end(live, fake_youtube, make_sample):
    """POST the URL, let the real dispatcher run the pipeline (yt-dlp faked), then GET the result."""
    client, dispatcher, events = live
    fake_youtube(make_sample(tone=True))
    project_id = new_project(client)

    accepted = client.post(f"/projects/{project_id}/ingestions/url", json={"url": SAMPLE_URL})
    dispatcher.join(JOIN_TIMEOUT_SECONDS)
    body = client.get(f"/projects/{project_id}/ingestion").json()

    assert accepted.status_code == 202
    assert (body["job"]["status"], body["job"]["progress"], body["job"]["message"]) == (
        "completed", 100, "Ingestion completed"
    )
    assert body["metadata"]["source"] == SAMPLE_URL
    assert body["metadata"]["aspect_ratio"] == "4:3"
    assert [str(event.project_id) for event in events] == [project_id]


def test_failed_ingestion_reports_error_details(live, fake_youtube, make_sample):
    client, dispatcher, events = live
    fake_youtube(make_sample())  # silent audio
    project_id = new_project(client)

    client.post(f"/projects/{project_id}/ingestions/url", json={"url": SAMPLE_URL})
    dispatcher.join(JOIN_TIMEOUT_SECONDS)
    body = client.get(f"/projects/{project_id}/ingestion").json()

    assert (body["job"]["status"], body["job"]["error_code"]) == ("failed", "silent_audio")
    assert "silent" in body["job"]["error_message"]
    assert client.get(f"/projects/{project_id}").json()["status"] == "ingestion_failed"
    assert body["metadata"] is None
    assert events == []


def test_unreachable_broker_answers_503_and_fails_the_job(client):
    project_id = new_project(client)
    app.dependency_overrides[get_dispatcher] = lambda: UnreachableBrokerDispatcher()

    response = client.post(f"/projects/{project_id}/ingestions/url", json={"url": SAMPLE_URL})

    assert response.status_code == 503
    assert response.json()["detail"] == "The job could not be queued; please try again."
    job = client.get(f"/projects/{project_id}/ingestion").json()["job"]
    assert (job["status"], job["error_code"]) == ("failed", "internal_error")
