import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.storage.local import LocalStorage, get_storage
from app.services.workflow.dispatcher import InProcessDispatcher, get_dispatcher

CHUNK_SIZE = 4096
JOIN_TIMEOUT_SECONDS = 60


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch):
    monkeypatch.setenv("UPLOAD_CHUNK_SIZE_BYTES", str(CHUNK_SIZE))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def live(storage):
    """Client wired to the real dispatcher; yields (client, dispatcher, published events)."""
    events = []
    dispatcher = InProcessDispatcher(storage, publish_event=events.append)
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    yield TestClient(app), dispatcher, events
    dispatcher.join(JOIN_TIMEOUT_SECONDS)
    app.dependency_overrides.clear()


def new_project(client, licence=True):
    response = client.post(
        "/projects", json={"title": "Lecture", "licence_confirmed": licence, "authorship_confirmed": True}
    )
    return response.json()["id"]


def start(client, project_id, file_name="Lecture 1.mp4", size_bytes=10_000, content_type="video/mp4"):
    return client.post(
        f"/projects/{project_id}/uploads",
        json={"file_name": file_name, "size_bytes": size_bytes, "content_type": content_type},
    )


def put_chunk(client, project_id, upload_id, index, data):
    return client.put(
        f"/projects/{project_id}/uploads/{upload_id}/chunks/{index}",
        files={"chunk": ("blob", data, "application/octet-stream")},
    )


def upload_all(client, project_id, data, file_name="Lecture 1.mp4"):
    """Send a whole file in chunks, last chunk first (order must not matter); return the upload ID."""
    upload_id = start(client, project_id, file_name=file_name, size_bytes=len(data)).json()["upload_id"]
    chunks = [data[offset:offset + CHUNK_SIZE] for offset in range(0, len(data), CHUNK_SIZE)]
    for index in reversed(range(len(chunks))):
        assert put_chunk(client, project_id, upload_id, index, chunks[index]).status_code == 204
    return upload_id


def test_start_upload_returns_chunk_plan(live):
    client, _, _ = live
    project_id = new_project(client)

    response = start(client, project_id, size_bytes=10_000)

    assert response.status_code == 201
    body = response.json()
    assert (body["chunk_size"], body["total_chunks"]) == (CHUNK_SIZE, 3)
    assert body["missing_chunks"] == [0, 1, 2]


@pytest.mark.parametrize("file_name, size_bytes, content_type, message", [
    ("notes.pdf", 10_000, "application/pdf", "extension 'pdf'"),
    ("talk", 10_000, None, "extension ''"),
    ("talk.mp4", 10_000, "image/png", "MIME type"),
    ("talk.mp4", 0, "video/mp4", "empty"),
    ("talk.mp4", 21 * 1024**3, "video/mp4", "exceeds the upload limit"),
])
def test_start_upload_rejects_declared_file(live, file_name, size_bytes, content_type, message):
    client, _, _ = live

    response = start(client, new_project(client), file_name, size_bytes, content_type)

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_start_upload_accepts_missing_mime_type(live):
    client, _, _ = live

    assert start(client, new_project(client), "Debate.MKV", content_type=None).status_code == 201


def test_start_upload_without_licence_is_forbidden(live):
    client, _, _ = live

    assert start(client, new_project(client, licence=False)).status_code == 403


def test_start_upload_for_unknown_project_is_not_found(live):
    client, _, _ = live

    assert start(client, str(uuid.uuid4())).status_code == 404


def test_chunks_are_tracked_and_can_be_resent(live):
    client, _, _ = live
    project_id = new_project(client)
    upload_id = start(client, project_id, size_bytes=10_000).json()["upload_id"]

    put_chunk(client, project_id, upload_id, 1, b"a" * CHUNK_SIZE)
    put_chunk(client, project_id, upload_id, 1, b"b" * CHUNK_SIZE)  # retry replaces it

    progress = client.get(f"/projects/{project_id}/uploads/{upload_id}").json()
    assert progress["missing_chunks"] == [0, 2]


@pytest.mark.parametrize("index, size, message", [
    (0, CHUNK_SIZE - 1, "must be 4096 bytes"),
    (0, CHUNK_SIZE + 1, "must be 4096 bytes"),
    (2, CHUNK_SIZE, "must be 1808 bytes"),  # the last chunk holds the remainder
    (3, 10, "out of range"),
])
def test_wrong_chunk_is_rejected(live, index, size, message):
    client, _, _ = live
    project_id = new_project(client)
    upload_id = start(client, project_id, size_bytes=10_000).json()["upload_id"]

    response = put_chunk(client, project_id, upload_id, index, b"x" * size)

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert client.get(f"/projects/{project_id}/uploads/{upload_id}").json()["missing_chunks"] == [0, 1, 2]


@pytest.mark.parametrize("upload_id, code", [(str(uuid.uuid4()), 404), ("not-a-uuid", 422)])
def test_unknown_or_invalid_upload_id(live, upload_id, code):
    client, _, _ = live

    assert put_chunk(client, new_project(client), upload_id, 0, b"x").status_code == code


def test_complete_with_missing_chunks_is_conflict(live):
    client, _, _ = live
    project_id = new_project(client)
    upload_id = start(client, project_id, size_bytes=10_000).json()["upload_id"]
    put_chunk(client, project_id, upload_id, 0, b"x" * CHUNK_SIZE)

    response = client.post(f"/projects/{project_id}/uploads/{upload_id}/complete")

    assert response.status_code == 409
    assert "2 chunk(s) missing, starting at index 1" in response.json()["detail"]


def test_chunked_upload_is_assembled_and_ingested(live, storage, make_sample):
    """FR02 acceptance: a chunked upload is assembled and ingested asynchronously, end to end."""
    client, dispatcher, events = live
    project_id = new_project(client)
    data = make_sample(tone=True).read_bytes()
    upload_id = upload_all(client, project_id, data)

    accepted = client.post(f"/projects/{project_id}/uploads/{upload_id}/complete")
    dispatcher.join(JOIN_TIMEOUT_SECONDS)
    body = client.get(f"/projects/{project_id}/ingestion").json()

    assert accepted.status_code == 202
    assert accepted.json()["stage"] == "queued"
    assert body["status"]["stage"] == "completed"
    assert body["metadata"]["source"] == "Lecture 1.mp4"
    assert storage.path(project_id, "source", f"{upload_id}.mp4").read_bytes() == data
    assert not (storage.project_dir(project_id) / "uploads" / upload_id).exists()
    assert len(events) == 1


def test_renamed_non_video_file_fails_inspection(live):
    """Extension and MIME only pass the first check; the content is still inspected (FR02 step 3)."""
    client, dispatcher, _ = live
    project_id = new_project(client)
    upload_id = upload_all(client, project_id, b"not a video" * 1000, file_name="fake.mp4")

    client.post(f"/projects/{project_id}/uploads/{upload_id}/complete")
    dispatcher.join(JOIN_TIMEOUT_SECONDS)

    status = client.get(f"/projects/{project_id}/ingestion").json()["status"]
    assert (status["stage"], status["error"]["code"]) == ("ingestion_failed", "processing_failed")


def test_complete_can_be_retried_after_conflict(live, make_sample):
    client, dispatcher, _ = live
    project_id = new_project(client)
    upload_id = upload_all(client, project_id, make_sample(tone=True).read_bytes())
    dispatcher.is_running = lambda pid: True  # pretend another job of this project is running

    refused = client.post(f"/projects/{project_id}/uploads/{upload_id}/complete")
    del dispatcher.is_running
    retried = client.post(f"/projects/{project_id}/uploads/{upload_id}/complete")

    assert (refused.status_code, retried.status_code) == (409, 202)
