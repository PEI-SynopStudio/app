import io
import os
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import boto3
import pytest

from app.core.config import get_settings
from app.services.storage import object_storage as object_storage_module
from app.services.storage.object_storage import ObjectStorageError, S3ObjectStorage, get_object_storage

TEST_S3_ENDPOINT_URL = os.environ.get("TEST_S3_ENDPOINT_URL", "http://localhost:8333")
TEST_S3_ACCESS_KEY = os.environ.get("TEST_S3_ACCESS_KEY", "pei")
TEST_S3_SECRET_KEY = os.environ.get("TEST_S3_SECRET_KEY", "pei")
UNREACHABLE_ENDPOINT = "http://127.0.0.1:1"
MULTIPART_SIZE_BYTES = 9 * 1024**2  # above the 8 MiB from which boto3 switches to a multipart upload
MIN_CHUNK_SIZE_BYTES = 5 * 1024**2  # the S3 API refuses smaller parts, except the last


def seaweedfs_is_running():
    try:
        urllib.request.urlopen(f"{TEST_S3_ENDPOINT_URL}/healthz", timeout=2).close()
    except OSError:
        return False
    return True


def direct_client():
    return boto3.client(
        "s3",
        endpoint_url=TEST_S3_ENDPOINT_URL,
        aws_access_key_id=TEST_S3_ACCESS_KEY,
        aws_secret_access_key=TEST_S3_SECRET_KEY,
        region_name="us-east-1",
    )


@pytest.fixture
def bucket():
    """A bucket of this test only, removed at the end."""
    if not seaweedfs_is_running():
        pytest.skip("SeaweedFS is not available; run 'docker compose up -d seaweedfs' first")
    name = f"pei-test-{uuid.uuid4().hex}"
    yield name
    client = direct_client()
    for upload in client.list_multipart_uploads(Bucket=name).get("Uploads", []):
        client.abort_multipart_upload(Bucket=name, Key=upload["Key"], UploadId=upload["UploadId"])
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=name):
        for item in page.get("Contents", []):
            client.delete_object(Bucket=name, Key=item["Key"])
    client.delete_bucket(Bucket=name)


@pytest.fixture
def storage(bucket):
    store = S3ObjectStorage(TEST_S3_ENDPOINT_URL, TEST_S3_ACCESS_KEY, TEST_S3_SECRET_KEY, bucket)
    store.ensure_bucket()
    return store


@pytest.fixture
def project_id():
    return str(uuid.uuid4())


def read_object(bucket, project_id, key):
    return direct_client().get_object(Bucket=bucket, Key=f"projects/{project_id}/{key}")["Body"].read()


def object_keys(bucket):
    return [item["Key"] for item in direct_client().list_objects_v2(Bucket=bucket).get("Contents", [])]


def local_file(tmp_path, data, name="file.bin"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_ensure_bucket_can_be_called_again(storage):
    storage.ensure_bucket()


def test_put_file_stores_the_content_under_the_project(storage, bucket, project_id, tmp_path):
    storage.put_file(project_id, "proxy/proxy.mp4", local_file(tmp_path, b"video"))

    assert object_keys(bucket) == [f"projects/{project_id}/proxy/proxy.mp4"]
    assert read_object(bucket, project_id, "proxy/proxy.mp4") == b"video"


def test_put_file_keeps_a_large_file_intact(storage, bucket, project_id, tmp_path):
    data = os.urandom(MULTIPART_SIZE_BYTES)

    storage.put_file(project_id, "source/lecture.mp4", local_file(tmp_path, data))

    assert read_object(bucket, project_id, "source/lecture.mp4") == data


def test_put_file_replaces_the_previous_object(storage, bucket, project_id, tmp_path):
    storage.put_file(project_id, "audio/audio.wav", local_file(tmp_path, b"old"))
    storage.put_file(project_id, "audio/audio.wav", local_file(tmp_path, b"new"))

    assert read_object(bucket, project_id, "audio/audio.wav") == b"new"


def test_put_file_rejects_a_missing_file(storage, project_id, tmp_path):
    with pytest.raises(FileNotFoundError):
        storage.put_file(project_id, "source/lecture.mp4", tmp_path / "missing.mp4")


def test_delete_removes_only_that_object(storage, bucket, project_id, tmp_path):
    path = local_file(tmp_path, b"data")
    storage.put_file(project_id, "audio/audio.wav", path)
    storage.put_file(project_id, "proxy/proxy.mp4", path)

    storage.delete(project_id, "audio/audio.wav")

    assert object_keys(bucket) == [f"projects/{project_id}/proxy/proxy.mp4"]


def test_delete_of_a_missing_object_is_not_an_error(storage, project_id):
    storage.delete(project_id, "audio/audio.wav")


def test_delete_project_keeps_the_other_projects(storage, bucket, project_id, tmp_path):
    other_project = str(uuid.uuid4())
    path = local_file(tmp_path, b"data")
    storage.put_file(project_id, "audio/audio.wav", path)
    storage.put_file(project_id, "analysis/waveform.json", path)
    storage.put_file(other_project, "audio/audio.wav", path)

    storage.delete_project(project_id)

    assert object_keys(bucket) == [f"projects/{other_project}/audio/audio.wav"]


def test_delete_project_without_objects_is_not_an_error(storage, project_id):
    storage.delete_project(project_id)


def test_delete_project_reports_objects_that_were_not_deleted(storage, project_id, tmp_path, monkeypatch):
    storage.put_file(project_id, "audio/audio.wav", local_file(tmp_path, b"data"))
    monkeypatch.setattr(
        storage._client, "delete_objects", lambda **_: {"Errors": [{"Key": "audio/audio.wav", "Code": "InternalError"}]}
    )

    with pytest.raises(ObjectStorageError):
        storage.delete_project(project_id)


@pytest.mark.parametrize("invalid_id", ["not-a-uuid", "../other", ""])
def test_invalid_project_id_is_rejected(storage, invalid_id, tmp_path):
    with pytest.raises(ValueError):
        storage.put_file(invalid_id, "audio/audio.wav", local_file(tmp_path, b"data"))


def fetch(url, headers=None):
    """Status, headers and body of a request made the way a browser follows a link, with no credentials."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, b""


def test_signed_url_serves_the_object_with_its_content_type(storage, project_id, tmp_path):
    storage.put_file(project_id, "proxy/proxy.mp4", local_file(tmp_path, b"video"))

    status, headers, body = fetch(storage.signed_url(project_id, "proxy/proxy.mp4", "video/mp4", 60))

    assert (status, headers["Content-Type"], body) == (200, "video/mp4", b"video")


def test_signed_url_supports_range_requests_on_encrypted_data(storage, project_id, tmp_path):
    data = os.urandom(MULTIPART_SIZE_BYTES)
    storage.put_file(project_id, "proxy/proxy.mp4", local_file(tmp_path, data))
    url = storage.signed_url(project_id, "proxy/proxy.mp4", "video/mp4", 60)

    status, _, body = fetch(url, {"Range": "bytes=8388000-8389000"})

    assert (status, body) == (206, data[8388000:8389001])


def test_signed_url_stops_working_when_it_expires(storage, project_id, tmp_path):
    storage.put_file(project_id, "proxy/proxy.mp4", local_file(tmp_path, b"video"))
    url = storage.signed_url(project_id, "proxy/proxy.mp4", "video/mp4", 1)

    time.sleep(3)

    assert fetch(url)[0] == 403


def test_signed_url_only_opens_the_object_it_was_signed_for(storage, project_id, tmp_path):
    path = local_file(tmp_path, b"video")
    storage.put_file(project_id, "proxy/proxy.mp4", path)
    storage.put_file(project_id, "source/lecture.mp4", path)
    url = storage.signed_url(project_id, "proxy/proxy.mp4", "video/mp4", 60)

    assert fetch(url.replace("proxy/proxy.mp4", "source/lecture.mp4"))[0] == 403


def test_signed_url_uses_the_public_address(project_id):
    store = S3ObjectStorage(UNREACHABLE_ENDPOINT, "key", "secret", "bucket", "https://media.example.org")

    assert store.signed_url(project_id, "proxy/proxy.mp4", "video/mp4", 60).startswith(
        f"https://media.example.org/bucket/projects/{project_id}/proxy/proxy.mp4?"
    )


def open_upload_ids(bucket):
    return [upload["UploadId"] for upload in direct_client().list_multipart_uploads(Bucket=bucket).get("Uploads", [])]


def test_get_file_copies_a_large_object_to_disk(storage, project_id, tmp_path):
    data = os.urandom(MULTIPART_SIZE_BYTES)
    storage.put_file(project_id, "source/lecture.mp4", local_file(tmp_path, data))

    storage.get_file(project_id, "source/lecture.mp4", tmp_path / "copy.mp4")

    assert (tmp_path / "copy.mp4").read_bytes() == data


def test_get_file_reports_a_missing_object(storage, project_id, tmp_path):
    with pytest.raises(ObjectStorageError):
        storage.get_file(project_id, "source/missing.mp4", tmp_path / "copy.mp4")


def test_chunks_sent_out_of_order_are_joined_in_order(storage, bucket, project_id):
    first, second = b"1" * MIN_CHUNK_SIZE_BYTES, b"2" * MIN_CHUNK_SIZE_BYTES
    upload_id = storage.start_chunked_upload(project_id, "source/lecture.mp4")
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 2, io.BytesIO(b"last"))
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 0, io.BytesIO(first))
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 1, io.BytesIO(second))

    storage.complete_chunked_upload(project_id, "source/lecture.mp4", upload_id)

    assert read_object(bucket, project_id, "source/lecture.mp4") == first + second + b"last"
    assert open_upload_ids(bucket) == []


def test_a_small_chunk_that_is_not_the_last_is_refused(storage, project_id):
    upload_id = storage.start_chunked_upload(project_id, "source/lecture.mp4")
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 0, io.BytesIO(b"too small"))
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 1, io.BytesIO(b"last"))

    with pytest.raises(ObjectStorageError):
        storage.complete_chunked_upload(project_id, "source/lecture.mp4", upload_id)


def test_received_chunks_lists_only_what_arrived(storage, project_id):
    upload_id = storage.start_chunked_upload(project_id, "source/lecture.mp4")
    assert storage.received_chunks(project_id, "source/lecture.mp4", upload_id) == set()

    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 0, io.BytesIO(b"a"))
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 3, io.BytesIO(b"b"))

    assert storage.received_chunks(project_id, "source/lecture.mp4", upload_id) == {0, 3}


def test_sending_a_chunk_again_replaces_it(storage, bucket, project_id):
    upload_id = storage.start_chunked_upload(project_id, "source/lecture.mp4")
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 0, io.BytesIO(b"old-old-old"))
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 0, io.BytesIO(b"new"))

    storage.complete_chunked_upload(project_id, "source/lecture.mp4", upload_id)

    assert read_object(bucket, project_id, "source/lecture.mp4") == b"new"


def test_a_chunk_can_come_from_an_uploaded_temporary_file(storage, bucket, project_id):
    upload_id = storage.start_chunked_upload(project_id, "source/lecture.mp4")
    with tempfile.SpooledTemporaryFile(max_size=1) as chunk:
        chunk.write(b"spooled to disk, as FastAPI does")
        chunk.seek(0)
        storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 0, chunk)

    storage.complete_chunked_upload(project_id, "source/lecture.mp4", upload_id)

    assert read_object(bucket, project_id, "source/lecture.mp4") == b"spooled to disk, as FastAPI does"


def test_abort_discards_the_chunks_and_can_be_repeated(storage, bucket, project_id):
    upload_id = storage.start_chunked_upload(project_id, "source/lecture.mp4")
    storage.put_chunk(project_id, "source/lecture.mp4", upload_id, 0, io.BytesIO(b"a"))

    storage.abort_chunked_upload(project_id, "source/lecture.mp4", upload_id)
    storage.abort_chunked_upload(project_id, "source/lecture.mp4", upload_id)

    assert open_upload_ids(bucket) == []
    assert object_keys(bucket) == []


def test_delete_project_also_discards_its_open_uploads(storage, bucket, project_id):
    other_project = str(uuid.uuid4())
    storage.start_chunked_upload(project_id, "source/lecture.mp4")
    kept = storage.start_chunked_upload(other_project, "source/lecture.mp4")

    storage.delete_project(project_id)

    assert open_upload_ids(bucket) == [kept]


@pytest.mark.parametrize("variable, value", [
    ("UPLOAD_CHUNK_SIZE_BYTES", "1024"),
    ("MAX_UPLOAD_BYTES", str(100 * 1024**4)),
])
def test_a_chunk_size_outside_the_s3_limits_is_refused(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    get_settings.cache_clear()
    get_object_storage.cache_clear()
    try:
        with pytest.raises(ValueError, match="does not fit the S3 limits"):
            get_object_storage()
    finally:
        get_settings.cache_clear()
        get_object_storage.cache_clear()


def test_wrong_credentials_are_reported(storage, bucket, project_id, tmp_path):
    intruder = S3ObjectStorage(TEST_S3_ENDPOINT_URL, TEST_S3_ACCESS_KEY, "wrong-secret", bucket)

    with pytest.raises(ObjectStorageError):
        intruder.put_file(project_id, "audio/audio.wav", local_file(tmp_path, b"data"))


def test_unreachable_service_is_reported(project_id, monkeypatch):
    monkeypatch.setattr(object_storage_module, "S3_MAX_ATTEMPTS", 1)
    store = S3ObjectStorage(UNREACHABLE_ENDPOINT, "key", "secret", "bucket")

    with pytest.raises(ObjectStorageError):
        store.delete(project_id, "audio/audio.wav")
