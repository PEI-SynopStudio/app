from __future__ import annotations
import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Tuple

# --- Defaults for environment-dependent settings ---
DEFAULT_MEDIA_ROOT = "/data/media"
DEFAULT_RABBITMQ_URL = "amqp://pei:pei@rabbitmq:5672/"
DEFAULT_S3_ENDPOINT_URL = "http://seaweedfs:8333"
DEFAULT_S3_ACCESS_KEY = "pei"
DEFAULT_S3_SECRET_KEY = "pei"
DEFAULT_S3_BUCKET = "synopstudio-media"
DEFAULT_ALLOWED_SOURCE_DOMAINS = "youtube.com,youtu.be,vimeo.com"
DEFAULT_ALLOWED_EXTENSIONS = "mp4,mov,mkv,webm,avi"
DEFAULT_ALLOWED_VIDEO_CODECS = "h264,hevc,vp9,av1"
DEFAULT_ALLOWED_AUDIO_CODECS = "aac,mp3,opus,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le"
DEFAULT_MAX_DURATION_SECONDS = 4 * 3600
DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024**3
DEFAULT_UPLOAD_CHUNK_SIZE_BYTES = 8 * 1024**2
DEFAULT_UPLOAD_SESSION_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_SWEEP_INTERVAL_SECONDS = 60
DEFAULT_JOB_STALLED_AFTER_SECONDS = 30 * 60
# A download of a time range reports no progress, and a 4 h range can take as long as the video itself.
DEFAULT_JOB_DOWNLOAD_STALLED_AFTER_SECONDS = 5 * 3600
DEFAULT_LOG_LEVEL = "INFO"
LIST_SEPARATOR = ","
DEFAULT_WHISPER_MODEL = "openai/whisper-large-v3-turbo"
DEFAULT_LANGUAGE = "pt"
DEFAULT_DATABASE_URL = "postgresql+psycopg2://pei:pei@postgres:5432/pei"
DEFAULT_DATABASE_ECHO = "false"
ENV_TRUE_VALUE = "true"


# --- Storage layout ---
PROJECTS_DIR = "projects"
TMP_SUFFIX = ".tmp"

# --- Object storage: SeaweedFS through its S3 API (architecture §2) ---
S3_SERVICE_NAME = "s3"
S3_REGION = "us-east-1"  # SeaweedFS ignores it, but request signatures need one
S3_SIGNATURE_VERSION = "s3v4"
S3_ADDRESSING_STYLE = "path"
S3_RETRY_MODE = "standard"
# SeaweedFS can report itself healthy a few seconds before its filer and volumes are ready.
S3_MAX_ATTEMPTS = 10
S3_KEY_SEPARATOR = "/"
S3_BUCKET_EXISTS_CODES = ("BucketAlreadyOwnedByYou", "BucketAlreadyExists")
ERROR_S3_BUCKET_FAILED = "Could not create the object storage bucket {bucket!r}."
ERROR_S3_PUT_FAILED = "Could not store the object {key!r}."
ERROR_S3_DELETE_FAILED = "Could not delete the object {key!r}."
ERROR_S3_DELETE_PROJECT_FAILED = "Could not delete the objects of project {project_id}."
ERROR_STORAGE_UNAVAILABLE = "The storage service is unavailable; please try again."
LOG_STORAGE_UNAVAILABLE = "Object storage request failed"

# --- Error messages ---
ERROR_INVALID_PROJECT_ID = "Invalid project ID: {project_id!r}"
ERROR_PROJECT_NOT_FOUND = "Project not found: {project_id}"
ERROR_PROJECT_BUSY = "Project {project_id} cannot be deleted while an ingestion is running."
ERROR_LICENCE_NOT_CONFIRMED = (
    "Ingestion refused: the project licence and authorship must be confirmed first."
)

# --- Project documents ---
JSON_DUMP_MODE = "json"
PROJECT_TITLE_MIN_LENGTH = 1
PROJECT_TITLE_MAX_LENGTH = 300
PROJECT_FIELD_MIN_LENGTH = 1
PROJECT_MIN_SPEAKERS = 1

# --- API ---
APP_TITLE = "PEI API"
# Only the application's own loggers ("app.*"); uvicorn and the media libraries keep their settings.
APP_LOGGER_NAME = "app"
LOG_FORMAT = "%(levelname)s:     %(name)s - %(message)s"
HEALTH_ROUTE = "/health"
HEALTH_OK = "ok"
ROUTE_ROOT = ""
PROJECTS_ROUTE_PREFIX = "/projects"
PROJECTS_ROUTE_TAG = "projects"
PROJECT_ID_ROUTE = "/{project_id}"
INGESTION_ROUTE_TAG = "ingestion"
URL_INGESTION_ROUTE = "/{project_id}/ingestions/url"
INGESTION_STATUS_ROUTE = "/{project_id}/ingestion"
URL_MAX_LENGTH = 2048
TIMECODE_MAX_LENGTH = 16
ERROR_INGESTION_NOT_STARTED = "No ingestion has been started for project {project_id}."
UPLOADS_ROUTE = "/{project_id}/uploads"
UPLOAD_ROUTE = "/{project_id}/uploads/{upload_id}"
UPLOAD_CHUNK_ROUTE = "/{project_id}/uploads/{upload_id}/chunks/{index}"
UPLOAD_COMPLETE_ROUTE = "/{project_id}/uploads/{upload_id}/complete"
JOBS_ROUTE_TAG = "jobs"
JOB_ROUTE = "/{project_id}/jobs/{job_id}"
PROGRESS_WS_ROUTE = "/{project_id}/progress"
# Application close codes start at 4000; 4404 mirrors the HTTP 404.
WS_CLOSE_PROJECT_NOT_FOUND = 4404
ASGI_WEBSOCKET_DISCONNECT = "websocket.disconnect"
PROGRESS_QUEUE_SIZE = 1
FILE_NAME_MIN_LENGTH = 1
FILE_NAME_MAX_LENGTH = 255
CONTENT_TYPE_MAX_LENGTH = 100


# --- Ingestion pipeline: per-project file layout ---
SOURCE_DIR = "source"
AUDIO_DIR = "audio"
PROXY_DIR = "proxy"
ANALYSIS_DIR = "analysis"
DOWNLOAD_FILE = "original.mp4"
AUDIO_FILE = "audio.wav"
PROXY_FILE = "proxy.mp4"
WAVEFORM_FILE = "waveform.json"
KEYFRAMES_FILE = "keyframes.json"
ERROR_INVALID_STAGED_FILE = "Invalid staged file name: {name!r}"
CUT_FILE_PREFIX = "cut-"
ERROR_CUT_FAILED = "Failed to cut the requested time range: {details}"
ERROR_INTERNAL = "Unexpected error during ingestion; see the worker logs."
LOG_INGESTION_FAILED = "Ingestion failed for project %s"

# --- Job dispatch and events ---
MEDIA_INGESTED_EVENT = "media.ingested"
ERROR_INGESTION_ALREADY_RUNNING = "An ingestion is already running for project {project_id}."
LOG_JOB_DISPATCH_FAILED = "Job %s could not be dispatched"
ERROR_JOB_DISPATCH_FAILED = "The job could not be queued; please try again."

# --- RabbitMQ: one durable queue per job type, bound to the jobs exchange (architecture §2) ---
JOBS_EXCHANGE = "jobs"
JOBS_QUEUE_FORMAT = "jobs.{job_type}"
JOB_EVENTS_EXCHANGE = "job_events"
JOB_EVENTS_QUEUE = "jobs.events"
JOB_EVENTS_ROUTING_KEY = "job.update"
MEDIA_EVENTS_EXCHANGE = "media_events"
MEDIA_INGESTED_QUEUE = "media.ingested"
EVENT_CONSUMER_PREFETCH = 1
EVENT_CONSUMER_RETRY_SECONDS = 5.0
LOG_EVENT_CONSUMER_UNAVAILABLE = "Job event consumer cannot reach the broker or the database, retrying: %s"
LOG_EVENT_INVALID = "Invalid job event discarded: %s"
LOG_EVENT_UNKNOWN_JOB = "Event for unknown job %s discarded"
LOG_EVENT_NOT_APPLIED = "Event of job %s could not be applied"
ERROR_JOB_STALLED = "The job stopped reporting progress; please submit it again."
LOG_SWEEP_DONE = "Sweep closed %d stalled job(s), %d abandoned upload(s)"
LOG_SWEEP_FAILED = "Periodic sweep failed"
BROKER_CONTENT_TYPE = "application/json"
# Below the 5 s the NFR allows for a job submission.
BROKER_PUBLISH_TIMEOUT_SECONDS = 3.0
WORKER_POLL_INTERVAL_SECONDS = 1.0
# Long enough for the broker to restart; after that the job is abandoned and the sweep marks it as timeout.
WORKER_EVENT_RETRY_SECONDS = 60.0
WORKER_EVENT_RETRY_INTERVAL_SECONDS = 1.0
LOG_WORKER_BROKER_UNAVAILABLE = "Broker unavailable, retrying: %s"
LOG_WORKER_INVALID_MESSAGE = "Invalid job message discarded: %s"
LOG_WORKER_JOB_CRASHED = "Job %s crashed in the worker"

# --- Chunked upload (FR02 step 1) ---
UPLOADS_DIR = "uploads"
UPLOAD_CHUNKS_DIR = "chunks"
CHUNK_FILE_FORMAT = "{index:06d}"
EXTENSION_SEPARATOR = "."
FILE_READ_MODE = "rb"
FILE_WRITE_MODE = "wb"
COPY_BUFFER_BYTES = 1024**2
# MIME types browsers report for the allowed containers; an empty type is accepted (the server inspects content).
ALLOWED_UPLOAD_MIME_TYPES = (
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "video/webm",
    "video/x-msvideo",
    "video/avi",
    "video/msvideo",
)
ERROR_UNSUPPORTED_EXTENSION = "File rejected: extension {extension!r} is not supported (allowed: {allowed})."
ERROR_UNSUPPORTED_MIME_TYPE = "File rejected: MIME type {content_type!r} is not a supported video type."
ERROR_UPLOAD_EMPTY = "File rejected: the file is empty."
ERROR_UPLOAD_TOO_LARGE = "File rejected: {size} bytes exceeds the upload limit of {limit} bytes."
ERROR_INVALID_UPLOAD_ID = "Invalid upload ID: {upload_id!r}"
ERROR_UPLOAD_NOT_FOUND = "Upload not found: {upload_id}"
ERROR_CHUNK_INDEX_OUT_OF_RANGE = "Chunk index {index} is out of range (0 to {last})."
ERROR_CHUNK_SIZE_MISMATCH = "Chunk {index} must be {expected} bytes, got {actual}."
ERROR_UPLOAD_INCOMPLETE = "Upload incomplete: {count} chunk(s) missing, starting at index {first}."


# --- yt-dlp (remote download) ---
YTDLP_MAX_HEIGHT = 1080
YTDLP_FORMAT_TEMPLATE = "bv*[height<={max_height}]+ba/b[height<={max_height}]"
YTDLP_FORMAT_SORT = ("vcodec:h264", "lang", "quality", "res", "fps", "hdr:12", "acodec:aac")
YTDLP_OUTPUT_CONTAINER = "mp4"
YTDLP_OUTPUT_TEMPLATE = "{stem}.%(ext)s"
YTDLP_REMUXER = "FFmpegVideoRemuxer"
YTDLP_DOWNLOADING_STATUS = "downloading"
YTDLP_FINISHED_STATUS = "finished"
ERROR_DOWNLOAD_FAILED = "Failed to download video with yt-dlp: {details}"

# --- Remote sources: URL validation and yt-dlp probe ---
ALLOWED_URL_SCHEMES = ("http", "https")
DOMAIN_SEPARATOR = "."
ALLOWED_AVAILABILITY = ("public", "unlisted")
REJECTED_LIVE_STATUSES = ("is_live", "is_upcoming", "post_live")
ERROR_INVALID_URL = "Invalid URL: only http and https links are accepted."
ERROR_DOMAIN_NOT_ALLOWED = "Source domain not allowed: {domain}"
ERROR_VIDEO_UNAVAILABLE = "Video is not accessible: {details}"
ERROR_VIDEO_NOT_PUBLIC = (
    "Video rejected: only public or unlisted videos can be imported (availability: {availability})."
)
ERROR_VIDEO_IS_LIVE = "Video rejected: live or upcoming streams can only be imported after they have ended."
ERROR_DURATION_UNKNOWN = "Video rejected: its duration could not be determined."
ERROR_DURATION_EXCEEDED = "Video rejected: duration {duration:.0f} s exceeds the limit of {limit} s."
ERROR_INVALID_TIMECODE = "Invalid timecode: {value!r}"
ERROR_INVALID_TIME_RANGE = (
    "Invalid time range: start ({start:.0f} s) must be before end ({end:.0f} s), "
    "and end must not exceed the video duration ({duration:.0f} s)."
)
VIDEO_START_SECONDS = 0.0

# --- Media inspection and audio normalization (PyAV) ---
STREAM_TYPE_AUDIO = "audio"
STREAM_TYPE_VIDEO = "video"
MEDIA_WRITE_MODE = "w"
AUDIO_SAMPLE_RATE = 16000
AUDIO_LAYOUT = "mono"
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_FORMAT = "s16"
AUDIO_CODEC = "pcm_s16le"
AUDIO_CONTAINER = "wav"
ERROR_FILE_NOT_FOUND = "File not found: {path}"
ERROR_UNREADABLE_MEDIA = "Corrupted or unreadable media file: {details}"
ERROR_NO_AUDIO_STREAM = "Video rejected: does not contain any decodable audio stream."
ERROR_AUDIO_EXTRACTION_FAILED = "Failed to extract normalized audio: {details}"

# --- Supported formats (FR02 whitelist, checked on the server) ---
# PyAV reports the demuxer as a comma-separated list, e.g. "mov,mp4,m4a,3gp,3g2,mj2".
ALLOWED_CONTAINER_FORMATS = ("mov", "mp4", "matroska", "webm", "avi")
ERROR_UNSUPPORTED_CONTAINER = "Video rejected: container format {format_name!r} is not supported."
ERROR_UNSUPPORTED_VIDEO_CODEC = "Video rejected: video codec {codec!r} is not supported."
ERROR_UNSUPPORTED_AUDIO_CODEC = "Video rejected: audio codec {codec!r} is not supported."

# --- Packet scan during inspection (FR02 step 3) ---
# H.264 and HEVC reorder at most 16 frames; packets are put in presentation order inside this window.
VFR_REORDER_WINDOW = 32
# Consecutive frame intervals are irregular when they differ by more than this share of the shorter one
# and by more than the rounding of the timestamps (millisecond containers, also after a remux to MP4).
VFR_INTERVAL_TOLERANCE = 0.05
VFR_TIMESTAMP_ROUNDING_SECONDS = 0.0015
# Below this share of irregular intervals the source has dropped frames, not a variable frame rate.
VFR_MIN_IRREGULAR_SHARE = 0.02
TRUNCATION_TOLERANCE_SECONDS = 1.0
ERROR_CORRUPTED_PACKETS = "Video rejected: {count} corrupted packet(s) found in the file."
ERROR_TRUNCATED_MEDIA = "Video rejected: the file is incomplete, {missing:.1f} s of its declared duration are missing."

# --- Silence detection on the normalized WAV ---
SILENCE_THRESHOLD_DBFS = -50.0
SILENCE_WINDOW_SECONDS = 1
PCM_SAMPLE_TYPECODE = "h"
PCM_FULL_SCALE = 32768
DECIBEL_FACTOR = 20
DECIBEL_BASE = 10
WAV_READ_MODE = "rb"
WAV_BYTE_ORDER = "little"
ERROR_SILENT_AUDIO = (
    "Video rejected: the audio track is silent (no window louder than {threshold} dBFS)."
)

# --- Waveform and volume profile on the normalized WAV (FR02 step 4) ---
WAVEFORM_WINDOW_SECONDS = 0.1
WAVEFORM_DECIMALS = 4

# --- Technical metadata (FR02 step 6) ---
ASPECT_RATIO_FORMAT = "{numerator}:{denominator}"


class SourceType(str, Enum):
    UPLOAD = "upload"
    URL = "url"

# --- Proxy video (PyAV) ---
# Demuxers whose packets have no presentation time of their own, only the decode order.
CONTAINERS_WITHOUT_PRESENTATION_TIMES = ("avi",)
PROXY_MAX_HEIGHT = 720
EVEN_DIMENSION = 2
PROXY_CONTAINER = "mp4"
PROXY_MUXER_OPTIONS = {"movflags": "+faststart"}
PROXY_VIDEO_CODEC = "libx264"
PROXY_PIXEL_FORMAT = "yuv420p"
# sc_threshold 0: no extra keyframes at scene changes, so the spacing stays regular.
PROXY_VIDEO_OPTIONS = {"preset": "veryfast", "crf": "26", "sc_threshold": "0"}
PROXY_KEYFRAME_INTERVAL_SECONDS = 2.0
KEYFRAME_TIME_DECIMALS = 3
PROXY_AUDIO_CODEC = "aac"
PROXY_AUDIO_BITRATE = 128_000
PROXY_AUDIO_SAMPLE_FORMAT = "fltp"
PROXY_AUDIO_FRAME_SIZE = 1024
ERROR_NO_VIDEO_STREAM = "Video rejected: does not contain any video stream."
ERROR_PROXY_FAILED = "Failed to generate proxy video: {details}"
ERROR_KEYFRAME_INDEX_FAILED = "Failed to build the keyframe index: {details}"


# --- Asynchronous jobs (T3.13) ---
class JobTypeEnum(str, Enum):
    """The pipeline a job runs."""
    INGESTION = "ingestion"
    TRANSCRIPTION = "transcription"


class JobStatusEnum(str, Enum):
    """Global state machine of an asynchronous job."""
    PENDING = "pending"  # persisted in the database
    QUEUED = "queued"  # handed to the broker
    PROCESSING = "processing"  # running in a worker
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStepProcessingEnum(str, Enum):
    """Granular steps reported to the interface."""
    INITIALIZING = "initializing"  # creating the worker's temporary workspace
    DOWNLOADING_MEDIA = "downloading_media"
    INSPECTING_MEDIA = "inspecting_media"
    EXTRACTING_AUDIO = "extracting_audio"
    GENERATING_PROXY = "generating_proxy"  # proxy video and keyframes
    TRANSCRIBING = "transcribing"
    DIARIZING = "diarizing"  # who spoke when
    PERSISTING_RESULTS = "persisting_results"  # sending artefacts to storage and the database
    CLEANING_UP = "cleaning_up"  # removing temporary files
    FINISHED = "finished"


class JobErrorCodeEnum(str, Enum):
    """Stable error codes; the UI maps them to messages."""
    INVALID_SOURCE = "invalid_source"
    SOURCE_UNAVAILABLE = "source_unavailable"
    DURATION_LIMIT_EXCEEDED = "duration_limit_exceeded"
    CORRUPTED_MEDIA = "corrupted_media"
    NO_AUDIO_TRACK = "no_audio_track"
    UNSUPPORTED_FORMAT = "unsupported_format"
    SILENT_AUDIO = "silent_audio"
    INTERNAL_ERROR = "internal_error"
    TIMEOUT = "timeout"


class AcousticProfileEnum(str, Enum):
    """Acoustic context profile of a recording (FR04)."""
    LECTURE = "lecture"
    DEBATE = "debate"
    CONFERENCE = "conference"
    INTERVIEW = "interview"


ERROR_CODE_APP = "app_error"
ERROR_CODE_JOB_NOT_FOUND = "job_not_found"
ERROR_CODE_INVALID_TRANSITION = "invalid_state_transition"
ERROR_CODE_JOB_TERMINAL = "job_already_terminal"
ERROR_CODE_STALE_ATTEMPT = "stale_job_attempt"
ERROR_CODE_INVALID_STEP = "invalid_step"
ERROR_JOB_NOT_FOUND = "Job not found"
ERROR_INVALID_JOB_ID = "Invalid job ID: {job_id!r}"
ERROR_INVALID_TRANSITION = "Invalid transition: {current} -> {target}"
ERROR_JOB_ALREADY_TERMINAL = "Job is already in a final status ({status})."
ERROR_STALE_JOB_ATTEMPT = "Event from a past attempt ignored ({event_attempt} < {current_attempt})."
ERROR_INVALID_STEP = "Step '{step}' does not belong to pipeline '{job_type}'."
ERROR_JOB_SOURCE_REQUIRED = "Provide exactly one of source_url or media_id."
ERROR_JOB_TIME_ORDER = "time_end must be after time_start."
ERROR_EVENT_CODE_REQUIRED = "error_code is required when status=failed."
ERROR_EVENT_CODE_NOT_ALLOWED = "error_code is only allowed when status=failed."
ERROR_TIMECODE_SECONDS = "Seconds must be below 60: {value}"
ERROR_TIMECODE_MINUTES = "Minutes must be below 60: {value}"
TIMECODE_SEPARATOR = ":"
TIMECODE_PART_PATTERN = r"\d+(?:\.\d{1,3})?"
TIMECODE_PART_COUNTS = (1, 2, 3)
TIMECODE_HMS_PARTS = 3
SEXAGESIMAL_BASE = 60
LANGUAGE_CODE_PATTERN = r"^[a-z]{2}(-[A-Z]{2})?$"
PROGRESS_MIN = 0.0
PROGRESS_MAX = 100.0
FIRST_JOB_ATTEMPT = 1
# Progress messages shown to the user for each step (FR02 outputs).
JOB_STEP_MESSAGES = {
    JobStepProcessingEnum.INITIALIZING: "Preparing the video",
    JobStepProcessingEnum.DOWNLOADING_MEDIA: "Downloading from URL",
    JobStepProcessingEnum.INSPECTING_MEDIA: "Inspecting media",
    JobStepProcessingEnum.EXTRACTING_AUDIO: "Extracting audio",
    JobStepProcessingEnum.GENERATING_PROXY: "Generating preview video",
    JobStepProcessingEnum.PERSISTING_RESULTS: "Saving technical metadata",
    JobStepProcessingEnum.FINISHED: "Ingestion completed",
}
PROGRESS_DECIMALS = 2
# Every progress event is a database write, so a step reports at most once per interval.
PROGRESS_EMIT_INTERVAL_SECONDS = 2.0
# A job only reaches 100% when the worker reports it as completed.
JOB_RUNNING_PROGRESS_CAP = 99.0
# Share of the total progress (start, end) covered by each step of a pipeline.
JOB_STEP_WEIGHTS = {
    JobTypeEnum.INGESTION: {
        JobStepProcessingEnum.INITIALIZING: (0.0, 5.0),
        JobStepProcessingEnum.DOWNLOADING_MEDIA: (5.0, 45.0),
        JobStepProcessingEnum.INSPECTING_MEDIA: (45.0, 50.0),
        JobStepProcessingEnum.EXTRACTING_AUDIO: (50.0, 70.0),
        JobStepProcessingEnum.GENERATING_PROXY: (70.0, 90.0),
        JobStepProcessingEnum.PERSISTING_RESULTS: (90.0, 95.0),
        JobStepProcessingEnum.CLEANING_UP: (95.0, 100.0),
        JobStepProcessingEnum.FINISHED: (100.0, 100.0),
    },
    JobTypeEnum.TRANSCRIPTION: {
        JobStepProcessingEnum.INITIALIZING: (0.0, 5.0),
        JobStepProcessingEnum.TRANSCRIBING: (5.0, 65.0),
        JobStepProcessingEnum.DIARIZING: (65.0, 90.0),
        JobStepProcessingEnum.PERSISTING_RESULTS: (90.0, 95.0),
        JobStepProcessingEnum.CLEANING_UP: (95.0, 100.0),
        JobStepProcessingEnum.FINISHED: (100.0, 100.0),
    },
}
# The statuses a worker is allowed to report; pending and queued belong to the API.
WORKER_REPORTABLE_STATUSES = (
    JobStatusEnum.PROCESSING,
    JobStatusEnum.COMPLETED,
    JobStatusEnum.FAILED,
    JobStatusEnum.CANCELLED,
)


class ApplyOutcome(str, Enum):
    APPLIED = "applied"
    IGNORED = "ignored"
    REJECTED = "rejected"


EVENT_REJECTED_STATUS = "Workers cannot report status {status}."
EVENT_REJECTED_UNKNOWN_ATTEMPT = "Event from an unknown attempt."
EVENT_IGNORED_PAST_ATTEMPT = "Event from a past attempt."
EVENT_IGNORED_JOB_FINISHED = "Job already finished ({status})."
EVENT_IGNORED_OUT_OF_ORDER = "Event older than the most recent one."
EVENT_IGNORED_EARLIER_STEP = "Step precedes the current one."
EVENT_IGNORED_LOWER_PROGRESS = "Progress is below the current one."
EVENT_IGNORED_NO_CHANGE = "Event changes nothing."


# --- Database models (FR01, FR02) ---
class LicenseType(str, Enum):
    CREATIVE_COMMONS = "creative_commons"
    INSTITUTIONAL_PERMISSION = "institutional_permission"
    PUBLIC_DEBATE_RIGHTS = "public_debate_rights"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    INGESTION_FAILED = "ingestion_failed"


class MediaAssetStatus(str, Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


TABLE_PROJECTS = "projects"
TABLE_MEDIA_ASSETS = "media_assets"
TABLE_AUDIO_TRACKS = "audio_tracks"
FK_PROJECT_ID = f"{TABLE_PROJECTS}.id"
FK_MEDIA_ASSET_ID = f"{TABLE_MEDIA_ASSETS}.id"
DB_ON_DELETE_CASCADE = "CASCADE"
DB_DELETE_ORPHAN_CASCADE = "all, delete-orphan"
DB_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
ENUM_COLUMN_LENGTH = 64
OWNER_ID_MAX_LENGTH = 255
PROJECT_AUTHOR_MAX_LENGTH = 300
STORAGE_KEY_MAX_LENGTH = 1024
CONTAINER_NAME_MAX_LENGTH = 128
CODEC_NAME_MAX_LENGTH = 64
ASPECT_RATIO_MAX_LENGTH = 32
TABLE_UPLOAD_SESSIONS = "upload_sessions"
TABLE_JOBS = "jobs"
TABLE_AUDIT_LOG = "audit_log"
DB_ON_DELETE_SET_NULL = "SET NULL"
# A new ingestion replaces the assets in these statuses; uploads still in progress are kept.
REPLACEABLE_ASSET_STATUSES = (MediaAssetStatus.READY, MediaAssetStatus.FAILED)
JOB_ACTIVE_STATUSES = (JobStatusEnum.PENDING, JobStatusEnum.QUEUED, JobStatusEnum.PROCESSING)
JOB_ACTIVE_INGESTION_INDEX = "uq_jobs_one_active_ingestion_per_project"
ACTOR_HASH_MAX_LENGTH = 64
ERROR_AUDIT_LOG_IMMUTABLE = "Audit log entries cannot be changed or deleted."


class AuditAction(str, Enum):
    PROJECT_CREATED = "project.created"
    LICENCE_CONFIRMED = "licence.confirmed"
    UPLOAD_STARTED = "upload.started"
    INGESTION_REQUESTED = "ingestion.requested"
    INGESTION_COMPLETED = "ingestion.completed"
    INGESTION_FAILED = "ingestion.failed"
    PROJECT_DELETED = "project.deleted"


# Project fields copied to the audit log, which outlives the project (MS3 §1.4.3).
AUDIT_PROJECT_FIELDS = {"title"}
AUDIT_LICENCE_FIELDS = {"author", "license_type", "copyright_notice", "licence_confirmed", "authorship_confirmed"}
AUDIT_DETAIL_FILE_NAME = "file_name"
AUDIT_DETAIL_SIZE_BYTES = "size_bytes"
AUDIT_DETAIL_JOB_ID = "job_id"
AUDIT_DETAIL_SOURCE = "source"
AUDIT_DETAIL_ERROR_CODE = "error_code"
# Fields of a finished ingestion that are copied to its media asset (FR02 step 6).
ASSET_METADATA_FIELDS = (
    "container",
    "duration_seconds",
    "size_bytes",
    "width",
    "height",
    "aspect_ratio",
    "frame_rate",
    "is_vfr",
    "video_codec",
    "audio_codec",
    "sample_rate",
    "channels",
    "source_key",
    "proxy_key",
    "keyframes_key",
)
LOG_JOB_EVENT_REJECTED = "Event rejected for job %s: %s"


def _csv(name: str, default: str) -> Tuple[str, ...]:
    raw = os.environ.get(name, default)
    return tuple(item.strip().lower() for item in raw.split(LIST_SEPARATOR) if item.strip())


@dataclass(frozen=True)
class Settings:
    media_root: Path
    rabbitmq_url: str
    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    allowed_source_domains: Tuple[str, ...]
    allowed_extensions: Tuple[str, ...]
    allowed_video_codecs: Tuple[str, ...]
    allowed_audio_codecs: Tuple[str, ...]
    max_duration_seconds: int
    max_upload_bytes: int
    upload_chunk_size_bytes: int
    upload_session_ttl_seconds: int
    sweep_interval_seconds: int
    job_stalled_after_seconds: int
    job_download_stalled_after_seconds: int
    log_level: str
    whisper_model: str
    default_language: str
    database_url: str
    database_echo: bool


@lru_cache
def get_settings() -> Settings:
    """Load settings from environment variables (cached; call get_settings.cache_clear() after changing env)."""
    return Settings(
        media_root=Path(os.environ.get("MEDIA_ROOT", DEFAULT_MEDIA_ROOT)),
        rabbitmq_url=os.environ.get("RABBITMQ_URL", DEFAULT_RABBITMQ_URL),
        s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL", DEFAULT_S3_ENDPOINT_URL),
        s3_access_key=os.environ.get("S3_ACCESS_KEY", DEFAULT_S3_ACCESS_KEY),
        s3_secret_key=os.environ.get("S3_SECRET_KEY", DEFAULT_S3_SECRET_KEY),
        s3_bucket=os.environ.get("S3_BUCKET", DEFAULT_S3_BUCKET),
        allowed_source_domains=_csv("ALLOWED_SOURCE_DOMAINS", DEFAULT_ALLOWED_SOURCE_DOMAINS),
        allowed_extensions=_csv("ALLOWED_EXTENSIONS", DEFAULT_ALLOWED_EXTENSIONS),
        allowed_video_codecs=_csv("ALLOWED_VIDEO_CODECS", DEFAULT_ALLOWED_VIDEO_CODECS),
        allowed_audio_codecs=_csv("ALLOWED_AUDIO_CODECS", DEFAULT_ALLOWED_AUDIO_CODECS),
        max_duration_seconds=int(os.environ.get("MAX_DURATION_SECONDS", DEFAULT_MAX_DURATION_SECONDS)),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)),
        upload_chunk_size_bytes=int(os.environ.get("UPLOAD_CHUNK_SIZE_BYTES", DEFAULT_UPLOAD_CHUNK_SIZE_BYTES)),
        upload_session_ttl_seconds=int(os.environ.get("UPLOAD_SESSION_TTL_SECONDS", DEFAULT_UPLOAD_SESSION_TTL_SECONDS)),
        sweep_interval_seconds=int(os.environ.get("SWEEP_INTERVAL_SECONDS", DEFAULT_SWEEP_INTERVAL_SECONDS)),
        job_stalled_after_seconds=int(os.environ.get("JOB_STALLED_AFTER_SECONDS", DEFAULT_JOB_STALLED_AFTER_SECONDS)),
        job_download_stalled_after_seconds=int(
            os.environ.get("JOB_DOWNLOAD_STALLED_AFTER_SECONDS", DEFAULT_JOB_DOWNLOAD_STALLED_AFTER_SECONDS)
        ),
        log_level=os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
        whisper_model=os.environ.get("WHISPER_MODEL", DEFAULT_WHISPER_MODEL),
        default_language=os.environ.get("DEFAULT_LANGUAGE", DEFAULT_LANGUAGE),
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        database_echo=os.environ.get("DATABASE_ECHO", DEFAULT_DATABASE_ECHO).lower() == ENV_TRUE_VALUE,
    )