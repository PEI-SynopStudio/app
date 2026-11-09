import logging
import math
import os
import time
from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Tuple

from app.core.config import (
    ANALYSIS_DIR,
    AUDIO_DIR,
    AUDIO_FILE,
    CUT_FILE_PREFIX,
    DOWNLOAD_FILE,
    ERROR_DURATION_EXCEEDED,
    ERROR_INTERNAL,
    ERROR_INVALID_STAGED_FILE,
    ERROR_STORAGE_UNAVAILABLE,
    JSON_DUMP_MODE,
    KEYFRAMES_FILE,
    LOG_INGESTION_FAILED,
    LOG_UPLOAD_DISCARD_FAILED,
    PROGRESS_MAX,
    PROGRESS_EMIT_INTERVAL_SECONDS,
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
from app.services.storage.object_storage import ObjectStorage, ObjectStorageError
from app.services.video.ingestion import (
    MediaInfo,
    PacketScan,
    ProgressCallback,
    check_audio_not_silent,
    check_packet_integrity,
    check_supported_formats,
    cut_media,
    download_youtube_video,
    extract_normalized_audio,
    generate_keyframe_index,
    generate_proxy_video,
    generate_waveform,
    inspect_media,
    scan_packets,
)
from app.services.video.metadata import IngestionOutput, build_technical_metadata
from app.services.video.sources import probe_remote_video, validate_time_range
from app.services.video.uploads import source_key

logger = logging.getLogger(__name__)

EventEmitter = Callable[[JobUpdateEventSchema], None]


# Run FR02 steps 2–6 in order and report each step as an event; any failure ends in a failed event.
# Source: MS2 FR02 – Steps 2 to 6; architecture §4 step 2.
def run_ingestion(
    storage: LocalStorage, object_storage: ObjectStorage, request: JobRequestMessage, emit: EventEmitter
) -> JobUpdateEventSchema:
    """Blocking: call it from a worker, never from an endpoint. Returns the final event.

    Business-rule rejections and processing errors end in a failed event, which is returned.
    Unexpected errors emit a failed event as well, then are re-raised so the worker logs them.
    The project and its licence (FR01) are checked before the job exists: workers have no database access.
    The working files are removed before the final event, so nothing of the job stays outside the encrypted storage.
    """
    project_id = str(request.project_id)
    staged_key: Optional[str] = None  # known once the name of the staged file has been checked

    def publish(**fields) -> JobUpdateEventSchema:
        event = JobUpdateEventSchema(job_id=request.job_id, attempt=request.attempt, **fields)
        emit(event)
        return event

    def advance(step: JobStepProcessingEnum) -> ProgressCallback:
        """Announce a step and return the callback that reports the progress inside it."""
        publish(status=JobStatusEnum.PROCESSING, step=step, step_progress=PROGRESS_MIN)
        return _throttled(lambda percent: publish(status=JobStatusEnum.PROCESSING, step=step, step_progress=percent))

    def fail(code: JobErrorCodeEnum, message: str) -> JobUpdateEventSchema:
        storage.delete_project(project_id)
        if staged_key is not None:
            _discard_upload(object_storage, request, project_id, staged_key)
        return publish(status=JobStatusEnum.FAILED, step_progress=PROGRESS_MIN, error_code=code, error_message=message)

    try:
        advance(JobStepProcessingEnum.INITIALIZING)
        if request.parameters.source_url is None:
            staged_key = _staged_key(storage, request)
        source_path = _fetch_source(storage, object_storage, request, staged_key, advance)

        advance(JobStepProcessingEnum.INSPECTING_MEDIA)
        media, scan = _inspect_source(source_path)
        cut_start = None
        if request.parameters.source_url is None:
            params = request.parameters
            time_range = validate_time_range(params.time_start, params.time_end, media.duration_seconds or math.inf)
            if time_range is not None:
                cut_start = _cut_upload(source_path, *time_range)
                media, scan = _inspect_source(source_path)

        # Audio first: a silent recording is rejected before the proxy is encoded.
        report = advance(JobStepProcessingEnum.EXTRACTING_AUDIO)
        audio_path = extract_normalized_audio(source_path, storage.path(project_id, AUDIO_DIR, AUDIO_FILE), report)
        check_audio_not_silent(audio_path)
        generate_waveform(audio_path, storage.path(project_id, ANALYSIS_DIR, WAVEFORM_FILE))

        report = advance(JobStepProcessingEnum.GENERATING_PROXY)
        proxy_path = generate_proxy_video(source_path, storage.path(project_id, PROXY_DIR, PROXY_FILE), report)
        generate_keyframe_index(proxy_path, storage.path(project_id, ANALYSIS_DIR, KEYFRAMES_FILE))

        report = advance(JobStepProcessingEnum.PERSISTING_RESULTS)
        output = _build_output(storage, request, media, scan.is_vfr, source_path, cut_start)
        # An upload that was not cut is already in object storage.
        send_source = request.parameters.source_url is not None or cut_start is not None
        _store_results(storage, object_storage, project_id, output, send_source, report)
    except (MediaRejectedError, MediaProcessingError) as exc:
        return fail(exc.code, str(exc))
    except (ValueError, FileNotFoundError) as exc:
        return fail(JobErrorCodeEnum.INVALID_SOURCE, str(exc))
    except RuntimeError as exc:
        return fail(JobErrorCodeEnum.CORRUPTED_MEDIA, str(exc))
    except ObjectStorageError:
        logger.exception(LOG_INGESTION_FAILED, project_id)
        return fail(JobErrorCodeEnum.INTERNAL_ERROR, ERROR_STORAGE_UNAVAILABLE)
    except Exception:
        logger.exception(LOG_INGESTION_FAILED, project_id)
        fail(JobErrorCodeEnum.INTERNAL_ERROR, ERROR_INTERNAL)
        raise

    storage.delete_project(project_id)
    return publish(status=JobStatusEnum.COMPLETED, step_progress=PROGRESS_MAX, output=output.model_dump(mode=JSON_DUMP_MODE))


def _throttled(report: ProgressCallback) -> ProgressCallback:
    """Forward at most one update per interval; the media loops call this for every frame."""
    last_sent = time.monotonic()

    def forward(percent: float) -> None:
        nonlocal last_sent
        now = time.monotonic()
        if now - last_sent >= PROGRESS_EMIT_INTERVAL_SECONDS:
            last_sent = now
            report(percent)

    return forward


def _inspect_source(source_path: Path) -> Tuple[MediaInfo, PacketScan]:
    """Run the FR02 step 3 checks on a source file; raises when it must be rejected."""
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
    return media, scan


def _cut_upload(source_path: Path, start_seconds: float, end_seconds: float) -> float:
    """Replace an upload by its requested time range; returns where the kept part really starts."""
    partial_path = source_path.with_name(CUT_FILE_PREFIX + source_path.name)
    try:
        cut = cut_media(source_path, partial_path, start_seconds, end_seconds)
        os.replace(partial_path, source_path)
    finally:
        partial_path.unlink(missing_ok=True)
    return cut.start_seconds


def _staged_key(storage: LocalStorage, request: JobRequestMessage) -> str:
    """Return the storage key of the upload; only a file directly inside the source directory is accepted."""
    if not request.staged_file:
        raise ValueError(ERROR_INVALID_STAGED_FILE.format(name=request.staged_file))
    source_dir = storage.project_dir(str(request.project_id)) / SOURCE_DIR
    if (source_dir / request.staged_file).resolve().parent != source_dir.resolve():
        raise ValueError(ERROR_INVALID_STAGED_FILE.format(name=request.staged_file))
    return source_key(request.staged_file)


def _discard_upload(object_storage: ObjectStorage, request: JobRequestMessage, project_id: str, key: str) -> None:
    """A rejected upload does not stay in storage; if the storage is failing too, the failure is only logged."""
    try:
        if request.storage_upload_id is not None:
            object_storage.abort_chunked_upload(project_id, key, request.storage_upload_id)
        object_storage.delete(project_id, key)
    except ObjectStorageError:
        logger.exception(LOG_UPLOAD_DISCARD_FAILED, project_id)


def _fetch_source(
    storage: LocalStorage,
    object_storage: ObjectStorage,
    request: JobRequestMessage,
    staged_key: Optional[str],
    advance: Callable[[JobStepProcessingEnum], ProgressCallback],
) -> Path:
    """Return the local path of the source video: download it (URL) or join and fetch the upload."""
    project_id = str(request.project_id)
    params = request.parameters
    if params.source_url is not None:
        report = advance(JobStepProcessingEnum.DOWNLOADING_MEDIA)
        remote = probe_remote_video(str(params.source_url))
        validate_time_range(params.time_start, params.time_end, remote.duration_seconds)
        return download_youtube_video(
            remote.url,
            storage.path(project_id, SOURCE_DIR, DOWNLOAD_FILE),
            params.time_start,
            params.time_end,
            report,
        )

    if request.storage_upload_id is not None:
        object_storage.complete_chunked_upload(project_id, staged_key, request.storage_upload_id)
    source_path = storage.path(project_id, staged_key)
    object_storage.get_file(project_id, staged_key, source_path)
    return source_path


# Send what the job produced to object storage.
# Source: MS2 FR02 – Step 6; architecture §2 (workers read and write object storage directly).
def _store_results(
    storage: LocalStorage,
    object_storage: ObjectStorage,
    project_id: str,
    output: IngestionOutput,
    send_source: bool,
    report: ProgressCallback,
) -> None:
    """Objects left by a job that fails halfway cause no lasting harm.

    The next ingestion replaces them, and deleting the project removes everything under its prefix.
    """
    keys = [output.audio_key, output.proxy_key, output.waveform_key, output.keyframes_key]
    if send_source:
        keys.insert(0, output.source_key)
    for sent, key in enumerate(keys, start=1):
        object_storage.put_file(project_id, key, storage.path(project_id, key))
        report(PROGRESS_MAX * sent / len(keys))


def _build_output(
    storage: LocalStorage,
    request: JobRequestMessage,
    media: MediaInfo,
    is_vfr: bool,
    source_path: Path,
    cut_start: Optional[float],
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
        keyframes_key=PurePosixPath(ANALYSIS_DIR, KEYFRAMES_FILE).as_posix(),
        time_start_seconds=cut_start,
    )
