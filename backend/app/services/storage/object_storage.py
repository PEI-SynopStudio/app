import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import (
    ERROR_INVALID_PROJECT_ID,
    ERROR_S3_BUCKET_FAILED,
    ERROR_S3_DELETE_FAILED,
    ERROR_S3_DELETE_PROJECT_FAILED,
    ERROR_S3_PUT_FAILED,
    PROJECTS_DIR,
    S3_ADDRESSING_STYLE,
    S3_BUCKET_EXISTS_CODES,
    S3_KEY_SEPARATOR,
    S3_MAX_ATTEMPTS,
    S3_REGION,
    S3_RETRY_MODE,
    S3_SERVICE_NAME,
    S3_SIGNATURE_VERSION,
    get_settings,
)

_S3_ERRORS = (BotoCoreError, ClientError, S3UploadFailedError)


class ObjectStorageError(Exception):
    pass


class ObjectStorage(ABC):
    """Durable per-project storage; S3ObjectStorage is the implementation.

    Keys are relative to the project, as stored in the database (e.g. proxy/proxy.mp4).
    LocalStorage stays as the workers' scratch area, because PyAV and yt-dlp need local files.
    """

    @abstractmethod
    def put_file(self, project_id: str, key: str, path: Path) -> None:
        """Store a local file, replacing any object with the same key."""

    @abstractmethod
    def delete(self, project_id: str, key: str) -> None:
        """Remove an object of the project if it exists."""

    @abstractmethod
    def delete_project(self, project_id: str) -> None:
        """Remove every object of the project (US34)."""

    @abstractmethod
    def signed_url(self, project_id: str, key: str, content_type: str, expires_in_seconds: int) -> str:
        """Return a temporary link to an object, served with the given content type."""


# Keep the media of every project in one bucket of the S3 API, under projects/<project_id>/.
# Source: architecture §2 (object storage); MS2 NFR Security (AES-256 at rest, applied by SeaweedFS).
class S3ObjectStorage(ObjectStorage):
    """Calls are blocking: run them in workers or in threads, never directly in the event loop."""

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        public_endpoint_url: Optional[str] = None,
    ) -> None:
        self._bucket = bucket
        self._client = _s3_client(endpoint_url, access_key, secret_key)
        self._public_client = _s3_client(public_endpoint_url or endpoint_url, access_key, secret_key)

    def ensure_bucket(self) -> None:
        """Create the bucket when missing; safe to call on every start and from several services."""
        message = ERROR_S3_BUCKET_FAILED.format(bucket=self._bucket)
        with _translate_errors(message):
            try:
                self._client.create_bucket(Bucket=self._bucket)
            except ClientError as exc:
                if exc.response["Error"]["Code"] not in S3_BUCKET_EXISTS_CODES:
                    raise

    def put_file(self, project_id: str, key: str, path: Path) -> None:
        """Streams from disk; large files go as a multipart upload, so they are never held in memory."""
        object_key = _project_prefix(project_id) + key
        with _translate_errors(ERROR_S3_PUT_FAILED.format(key=object_key)):
            self._client.upload_file(str(path), self._bucket, object_key)

    def delete(self, project_id: str, key: str) -> None:
        object_key = _project_prefix(project_id) + key
        with _translate_errors(ERROR_S3_DELETE_FAILED.format(key=object_key)):
            self._client.delete_object(Bucket=self._bucket, Key=object_key)

    def delete_project(self, project_id: str) -> None:
        """Raises if any object could not be deleted: the S3 API reports those inside a successful response."""
        prefix = _project_prefix(project_id)
        message = ERROR_S3_DELETE_PROJECT_FAILED.format(project_id=project_id)
        with _translate_errors(message):
            for page in self._client.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=prefix):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    response = self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": objects})
                    if response.get("Errors"):
                        raise ObjectStorageError(message)

    def signed_url(self, project_id: str, key: str, content_type: str, expires_in_seconds: int) -> str:
        """Signed locally, without a request to the storage service."""
        return self._public_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": _project_prefix(project_id) + key, "ResponseContentType": content_type},
            ExpiresIn=expires_in_seconds,
        )


@lru_cache
def get_object_storage() -> S3ObjectStorage:
    settings = get_settings()
    storage = S3ObjectStorage(
        settings.s3_endpoint_url,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_bucket,
        settings.s3_public_endpoint_url,
    )
    storage.ensure_bucket()
    return storage


def _s3_client(endpoint_url: str, access_key: str, secret_key: str):
    # A session of its own: the default boto3 session is not safe to share between threads.
    return boto3.session.Session().client(
        S3_SERVICE_NAME,
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=S3_REGION,
        config=Config(
            signature_version=S3_SIGNATURE_VERSION,
            s3={"addressing_style": S3_ADDRESSING_STYLE},
            retries={"mode": S3_RETRY_MODE, "total_max_attempts": S3_MAX_ATTEMPTS},
        ),
    )


@contextmanager
def _translate_errors(message: str) -> Iterator[None]:
    try:
        yield
    except _S3_ERRORS as exc:
        raise ObjectStorageError(message) from exc


def _project_prefix(project_id: str) -> str:
    # Project IDs must be UUIDs, as in LocalStorage; the final separator keeps one project out of another's prefix.
    try:
        normalized = str(uuid.UUID(project_id))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(ERROR_INVALID_PROJECT_ID.format(project_id=project_id))
    return PROJECTS_DIR + S3_KEY_SEPARATOR + normalized + S3_KEY_SEPARATOR
