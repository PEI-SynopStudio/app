import logging
from pathlib import Path, PurePosixPath
from typing import Callable

from app.core.config import (
    ANALYSIS_DIR,
    AUDIO_DIR,
    AUDIO_FILE,
    DOWNLOAD_FILE,
    ERROR_DURATION_EXCEEDED,
    ERROR_FILE_NOT_FOUND,
    ERROR_INTERNAL,
    ERROR_INVALID_STAGED_FILE,
    ERROR_UPLOAD_TIME_RANGE_UNSUPPORTED,
    JSON_DUMP_MODE,
    LOG_INGESTION_FAILED,
    PROGRESS_MAX,
    PROGRESS_MIN,
    PROXY_DIR,
    PROXY_FILE,
    SOURCE_DIR,
    WAVEFORM_FILE,
    JobErrorCodeEnum,
    JobStatusEnum,
    JobStepProcessingEnum,
    SourceType,
    get_settings,
)
from app.core.exceptions import MediaProcessingError, MediaRejectedError
from app.schemas.job import JobRequestMessage, JobUpdateEventSchema
from app.services.storage.local import LocalStorage
from app.services.video.ingestion import (
    check_audio_not_silent,
    check_packet_integrity,
    check_supported_formats,
    download_youtube_video,
    extract_normalized_audio,
    generate_proxy_video,
    generate_waveform,
    inspect_media,
    scan_packets,
)
from app.services.video.metadata import IngestionOutput, build_technical_metadata
from app.services.video.sources import probe_remote_video, validate_time_range
from app.services.video.uploads import assemble_chunks

logger = logging.getLogger(__name__)

EventEmitter = Callable[[JobUpdateEventSchema], None]


# Run FR02 steps 2–6 in order and report each step as an event; any failure ends in a failed event.
# Source: MS2 FR02 – Steps 2 to 6; architecture §4 step 2.
def run_ingestion(storage: LocalStorage, request: JobRequestMessage, emit: EventEmitter) -> JobUpdateEventSchema:
    """Blocking: call it from a worker, never from an endpoint. Returns the final event.

    Business-rule rejections and processing errors end in a failed event, which is returned.
    Unexpected errors emit a failed event as well, then are re-raised so the worker logs them.
    The project and its licence (FR01) are checked before the job exists: workers have no database access.
    """
    project_id = str(request.project_id)

    def publish(**fields) -> JobUpdateEventSchema:
        event = JobUpdateEventSchema(job_id=request.job_id, attempt=request.attempt, **fields)
        emit(event)
        return event

    def advance(step: JobStepProcessingEnum) -> None:
        publish(status=JobStatusEnum.PROCESSING, step=step, step_progress=PROGRESS_MIN)

    def fail(code: JobErrorCodeEnum, message: str) -> JobUpdateEventSchema:
        return publish(status=JobStatusEnum.FAILED, step_progress=PROGRESS_MIN, error_code=code, error_message=message)

    try:
        advance(JobStepProcessingEnum.INITIALIZING)
        source_path = _fetch_source(storage, request, advance)

        advance(JobStepProcessingEnum.INSPECTING_MEDIA)
        media = inspect_media(source_path)
        check_supported_formats(media)
        limit = get_settings().max_duration_seconds
        if media.duration_seconds and media.duration_seconds > limit:
            raise MediaRejectedError(
                JobErrorCodeEnum.DURATION_LIMIT_EXCEEDED,
                ERROR_DURATION_EXCEEDED.format(duration=media.duration_seconds, limit=limit),
            )
        scan = scan_packets(source_path)
        check_packet_integrity(scan)

        # Audio first: a silent recording is rejected before the proxy is encoded.
        advance(JobStepProcessingEnum.EXTRACTING_AUDIO)
        audio_path = extract_normalized_audio(source_path, storage.path(project_id, AUDIO_DIR, AUDIO_FILE))
        check_audio_not_silent(audio_path)
        generate_waveform(audio_path, storage.path(project_id, ANALYSIS_DIR, WAVEFORM_FILE))

        advance(JobStepProcessingEnum.GENERATING_PROXY)
        generate_proxy_video(source_path, storage.path(project_id, PROXY_DIR, PROXY_FILE))

        advance(JobStepProcessingEnum.PERSISTING_RESULTS)
        output = _build_output(storage, request, media, scan.is_vfr, source_path)
    except (MediaRejectedError, MediaProcessingError) as exc:
        return fail(exc.code, str(exc))
    except (ValueError, FileNotFoundError) as exc:
        return fail(JobErrorCodeEnum.INVALID_SOURCE, str(exc))
    except RuntimeError as exc:
        return fail(JobErrorCodeEnum.CORRUPTED_MEDIA, str(exc))
    except Exception:
        logger.exception(LOG_INGESTION_FAILED, project_id)
        fail(JobErrorCodeEnum.INTERNAL_ERROR, ERROR_INTERNAL)
        raise

    return publish(status=JobStatusEnum.COMPLETED, step_progress=PROGRESS_MAX, output=output.model_dump(mode=JSON_DUMP_MODE))


def _fetch_source(
    storage: LocalStorage, request: JobRequestMessage, advance: Callable[[JobStepProcessingEnum], None]
) -> Path:
    """Return the path of the source video: download it (URL) or assemble and locate the upload."""
    project_id = str(request.project_id)
    params = request.parameters
    if params.source_url is not None:
        advance(JobStepProcessingEnum.DOWNLOADING_MEDIA)
        remote = probe_remote_video(str(params.source_url))
        validate_time_range(params.time_start, params.time_end, remote.duration_seconds)
        return download_youtube_video(
            remote.url,
            storage.path(project_id, SOURCE_DIR, DOWNLOAD_FILE),
            params.time_start,
            params.time_end,
        )

    if params.time_start is not None or params.time_end is not None:
        raise ValueError(ERROR_UPLOAD_TIME_RANGE_UNSUPPORTED)
    if not request.staged_file:
        raise ValueError(ERROR_INVALID_STAGED_FILE.format(name=request.staged_file))
    source_dir = storage.project_dir(project_id) / SOURCE_DIR
    source_path = source_dir / request.staged_file
    # Only a file directly inside the project's source directory is accepted (no "..", "/" or symlinks out).
    if source_path.resolve().parent != source_dir.resolve():
        raise ValueError(ERROR_INVALID_STAGED_FILE.format(name=request.staged_file))
    if request.upload_id is not None:
        assemble_chunks(storage, project_id, str(request.upload_id), request.staged_file)
    if not source_path.is_file():
        raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=request.staged_file))
    return source_path


def _build_output(
    storage: LocalStorage, request: JobRequestMessage, media, is_vfr: bool, source_path: Path
) -> IngestionOutput:
    """Collect what the backend persists when the job completes (FR02 step 6)."""
    url = request.parameters.source_url
    source_type = SourceType.URL if url is not None else SourceType.UPLOAD
    source = str(url) if url is not None else request.file_name
    metadata = build_technical_metadata(media, is_vfr, source_type, source)
    return IngestionOutput(
        **metadata.model_dump(),
        source_key=source_path.relative_to(storage.project_dir(str(request.project_id))).as_posix(),
        proxy_key=PurePosixPath(PROXY_DIR, PROXY_FILE).as_posix(),
        audio_key=PurePosixPath(AUDIO_DIR, AUDIO_FILE).as_posix(),
        waveform_key=PurePosixPath(ANALYSIS_DIR, WAVEFORM_FILE).as_posix(),
    )
