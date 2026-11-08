from fastapi import HTTPException, status

from app.core.exceptions import JobNotFoundError
from app.services.projects.projects import LicenceNotConfirmedError, ProjectBusyError, ProjectNotFoundError
from app.services.video.uploads import UploadIncompleteError, UploadNotFoundError
from app.services.workflow.jobs import IngestionAlreadyRunningError

# Service exceptions the API turns into HTTP errors; anything else stays a 500.
SERVICE_ERRORS = (
    ValueError,
    ProjectNotFoundError,
    LicenceNotConfirmedError,
    ProjectBusyError,
    IngestionAlreadyRunningError,
    JobNotFoundError,
    UploadNotFoundError,
    UploadIncompleteError,
)


def http_error(exc: Exception) -> HTTPException:
    """Map a service exception to an HTTP error that keeps its descriptive message."""
    if isinstance(exc, (ProjectNotFoundError, UploadNotFoundError, JobNotFoundError)):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, LicenceNotConfirmedError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, (IngestionAlreadyRunningError, UploadIncompleteError, ProjectBusyError)):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=str(exc))
