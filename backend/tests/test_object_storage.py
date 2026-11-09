import os
import urllib.request
import uuid

import boto3
import pytest

from app.services.storage import object_storage as object_storage_module
from app.services.storage.object_storage import ObjectStorageError, S3ObjectStorage

TEST_S3_ENDPOINT_URL = os.environ.get("TEST_S3_ENDPOINT_URL", "http://localhost:8333")
TEST_S3_ACCESS_KEY = os.environ.get("TEST_S3_ACCESS_KEY", "pei")
TEST_S3_SECRET_KEY = os.environ.get("TEST_S3_SECRET_KEY", "pei")
UNREACHABLE_ENDPOINT = "http://127.0.0.1:1"
MULTIPART_SIZE_BYTES = 9 * 1024**2  # above the 8 MiB from which boto3 switches to a multipart upload


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


def test_wrong_credentials_are_reported(storage, bucket, project_id, tmp_path):
    intruder = S3ObjectStorage(TEST_S3_ENDPOINT_URL, TEST_S3_ACCESS_KEY, "wrong-secret", bucket)

    with pytest.raises(ObjectStorageError):
        intruder.put_file(project_id, "audio/audio.wav", local_file(tmp_path, b"data"))


def test_unreachable_service_is_reported(project_id, monkeypatch):
    monkeypatch.setattr(object_storage_module, "S3_MAX_ATTEMPTS", 1)
    store = S3ObjectStorage(UNREACHABLE_ENDPOINT, "key", "secret", "bucket")

    with pytest.raises(ObjectStorageError):
        store.delete(project_id, "audio/audio.wav")
