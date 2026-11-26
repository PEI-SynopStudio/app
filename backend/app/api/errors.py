import logging

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core.config import (
    ERROR_IDENTITY_PROVIDER_UNAVAILABLE,
    ERROR_STORAGE_UNAVAILABLE,
    LOG_IDENTITY_PROVIDER_UNAVAILABLE,
    LOG_STORAGE_UNAVAILABLE,
)
from app.core.exceptions import JobDispatchError, JobNotFoundError, ConflictError, DomainValidationError
from app.services.auth.identity_provider import IdentityProviderError
from app.services.projects.projects import LicenceNotConfirmedError, ProjectBusyError, ProjectNotFoundError
from app.services.storage.object_storage import ObjectStorageError
from app.services.transcripts.transcripts import TranscriptAlreadyExistsError, TranscriptNotFoundError
from app.services.video.playback import MediaNotReadyError
from app.services.video.uploads import UploadIncompleteError, UploadNotFoundError
from app.services.workflow.jobs import IngestionAlreadyRunningError, TranscriptionAlreadyRunningError

logger = logging.getLogger(__name__)

# Service exceptions the API turns into HTTP errors; anything else stays a 500.
SERVICE_ERRORS = (
    ValueError,
    DomainValidationError,
    ConflictError,
    ProjectNotFoundError,
    LicenceNotConfirmedError,
    ProjectBusyError,
    IngestionAlreadyRunningError,
    TranscriptionAlreadyRunningError,
    JobNotFoundError,
    JobDispatchError,
    UploadNotFoundError,
    UploadIncompleteError,
    MediaNotReadyError,
    TranscriptNotFoundError,
    TranscriptAlreadyExistsError,
)


def http_error(exc: Exception) -> HTTPException:
    """Map a service exception to an HTTP error that keeps its descriptive message."""
    if isinstance(exc, (ProjectNotFoundError, UploadNotFoundError, JobNotFoundError, MediaNotReadyError, TranscriptNotFoundError)):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, LicenceNotConfirmedError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(
        exc,
        (
            IngestionAlreadyRunningError,
            TranscriptionAlreadyRunningError,
            TranscriptAlreadyExistsError,
            UploadIncompleteError,
            ProjectBusyError,
            ConflictError,
        ),
    ):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, JobDispatchError):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=str(exc))


def storage_unavailable(_: Request, exc: ObjectStorageError) -> JSONResponse:
    """Registered on the app: the error can also come from the dependency that opens the storage."""
    logger.error(LOG_STORAGE_UNAVAILABLE, exc_info=exc)
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": ERROR_STORAGE_UNAVAILABLE})


def identity_provider_unavailable(_: Request, exc: IdentityProviderError) -> JSONResponse:
    """Registered on the app: Keycloak can fail in any endpoint that ends sessions or deletes the account."""
    logger.error(LOG_IDENTITY_PROVIDER_UNAVAILABLE, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": ERROR_IDENTITY_PROVIDER_UNAVAILABLE}
    )
