import logging
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel

from app.core.config import (
    AUDIO_DIR,
    AUDIO_FILE,
    DOWNLOAD_FILE,
    ERROR_DURATION_EXCEEDED,
    ERROR_FILE_NOT_FOUND,
    ERROR_INTERNAL,
    ERROR_INVALID_STAGED_FILE,
    ERROR_UPLOAD_TIME_RANGE_UNSUPPORTED,
    LOG_INGESTION_FAILED,
    PROXY_DIR,
    PROXY_FILE,
    SOURCE_DIR,
    STAGE_MESSAGES,
    IngestionErrorCode,
    IngestionStage,
    SourceType,
    get_settings,
)
from app.services.projects.projects import LicenceNotConfirmedError, get_project, require_ingestion_allowed
from app.services.storage.local import LocalStorage
from app.services.video.ingestion import (
    check_audio_not_silent,
    check_supported_formats,
    download_youtube_video,
    extract_normalized_audio,
    generate_proxy_video,
    inspect_media,
)
from app.services.video.metadata import (
    build_technical_metadata,
    clear_technical_metadata,
    save_technical_metadata,
)
from app.services.video.sources import probe_remote_video, validate_time_range
from app.services.workflow.status import IngestionStatus, mark_failed, set_stage

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[IngestionStatus], None]


class IngestionJob(BaseModel):
    """One ingestion request; later this is the body of the RabbitMQ job message."""
    project_id: str
    source_type: SourceType
    # The original URL, or the original file name of an upload (kept in the metadata).
    source: str
    # Uploads only: name of the assembled file inside the project's source directory.
    staged_file: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


# Run FR02 steps 2–6 in order and record the stage after each one; any failure ends in 'Ingestion Failed'.
# Source: MS2 FR02 – Steps 2 to 6; architecture §4 step 2.
def run_ingestion(
    storage: LocalStorage, job: IngestionJob, on_progress: Optional[ProgressCallback] = None
) -> IngestionStatus:
    """Blocking: call it from a worker, never from an endpoint.

    Business-rule rejections and processing errors are stored as a failed status and returned.
    Unexpected errors are stored as well, then re-raised so the worker logs them.
    Raises ProjectNotFoundError (nothing is written) when the project does not exist.
    """
    project_id = job.project_id

    def advance(stage: IngestionStage) -> None:
        _notify(on_progress, set_stage(storage, project_id, stage, STAGE_MESSAGES[stage]))

    def fail(code: IngestionErrorCode, message: str) -> IngestionStatus:
        status = mark_failed(storage, project_id, code.value, message)
        _notify(on_progress, status)
        return status

    get_project(storage, project_id)
    # A new run replaces the previous one: its old metadata must not be shown next to the new status.
    clear_technical_metadata(storage, project_id)

    try:
        require_ingestion_allowed(storage, project_id)
    except LicenceNotConfirmedError as exc:
        return fail(IngestionErrorCode.LICENCE_NOT_CONFIRMED, str(exc))

    try:
        source_path = _fetch_source(storage, job, advance)

        advance(IngestionStage.INSPECTING)
        media = inspect_media(source_path)
        check_supported_formats(media)
        limit = get_settings().max_duration_seconds
        if media.duration_seconds and media.duration_seconds > limit:
            raise ValueError(ERROR_DURATION_EXCEEDED.format(duration=media.duration_seconds, limit=limit))

        # Audio first: a silent recording is rejected before the proxy is encoded.
        advance(IngestionStage.EXTRACTING_AUDIO)
        audio_path = extract_normalized_audio(source_path, storage.path(project_id, AUDIO_DIR, AUDIO_FILE))
        check_audio_not_silent(audio_path)

        advance(IngestionStage.GENERATING_PROXY)
        generate_proxy_video(source_path, storage.path(project_id, PROXY_DIR, PROXY_FILE))

        advance(IngestionStage.ANALYSING)
        save_technical_metadata(storage, project_id, build_technical_metadata(media, job.source_type, job.source))
    except (ValueError, FileNotFoundError) as exc:
        return fail(IngestionErrorCode.MEDIA_REJECTED, str(exc))
    except RuntimeError as exc:
        return fail(IngestionErrorCode.PROCESSING_FAILED, str(exc))
    except Exception:
        logger.exception(LOG_INGESTION_FAILED, project_id)
        fail(IngestionErrorCode.INTERNAL_ERROR, ERROR_INTERNAL)
        raise

    status = set_stage(storage, project_id, IngestionStage.COMPLETED, STAGE_MESSAGES[IngestionStage.COMPLETED])
    _notify(on_progress, status)
    return status


def _fetch_source(storage: LocalStorage, job: IngestionJob, advance: Callable[[IngestionStage], None]) -> Path:
    """Return the path of the source video: download it (URL) or locate the staged upload."""
    if job.source_type == SourceType.URL:
        advance(IngestionStage.DOWNLOADING)
        remote = probe_remote_video(job.source)
        validate_time_range(job.start_time, job.end_time, remote.duration_seconds)
        return download_youtube_video(
            remote.url,
            storage.path(job.project_id, SOURCE_DIR, DOWNLOAD_FILE),
            job.start_time,
            job.end_time,
        )

    if job.start_time is not None or job.end_time is not None:
        raise ValueError(ERROR_UPLOAD_TIME_RANGE_UNSUPPORTED)
    if not job.staged_file:
        raise ValueError(ERROR_INVALID_STAGED_FILE.format(name=job.staged_file))
    source_dir = storage.project_dir(job.project_id) / SOURCE_DIR
    source_path = source_dir / job.staged_file
    # Only a file directly inside the project's source directory is accepted (no "..", "/" or symlinks out).
    if source_path.resolve().parent != source_dir.resolve():
        raise ValueError(ERROR_INVALID_STAGED_FILE.format(name=job.staged_file))
    if not source_path.is_file():
        raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=job.staged_file))
    return source_path


def _notify(on_progress: Optional[ProgressCallback], status: IngestionStatus) -> None:
    if on_progress is not None:
        on_progress(status)
