import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Tuple

# --- Defaults for environment-dependent settings ---
DEFAULT_MEDIA_ROOT = "/data/media"
DEFAULT_RABBITMQ_URL = "amqp://pei:pei@rabbitmq:5672/"
DEFAULT_ALLOWED_SOURCE_DOMAINS = "youtube.com,youtu.be,vimeo.com"
DEFAULT_ALLOWED_EXTENSIONS = "mp4,mov,mkv,webm,avi"
DEFAULT_ALLOWED_VIDEO_CODECS = "h264,hevc,vp9,av1"
DEFAULT_ALLOWED_AUDIO_CODECS = "aac,mp3,opus,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le"
DEFAULT_MAX_DURATION_SECONDS = 4 * 3600
DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024**3
DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 6 * 3600
LIST_SEPARATOR = ","

# --- Storage layout ---
PROJECTS_DIR = "projects"
JSON_ENCODING = "utf-8"
JSON_INDENT = 2
TMP_SUFFIX = ".tmp"

# --- Error messages ---
ERROR_INVALID_PROJECT_ID = "Invalid project ID: {project_id!r}"
ERROR_PROJECT_NOT_FOUND = "Project not found: {project_id}"
ERROR_LICENCE_NOT_CONFIRMED = (
    "Ingestion refused: the project licence and authorship must be confirmed first."
)

# --- Project documents ---
PROJECT_FILE = "project.json"
INGESTION_STATUS_FILE = "ingestion.json"
JSON_DUMP_MODE = "json"
PROJECT_TITLE_MIN_LENGTH = 1
PROJECT_TITLE_MAX_LENGTH = 300

# --- API ---
APP_TITLE = "PEI API"
HEALTH_ROUTE = "/health"
HEALTH_OK = "ok"
ROUTE_ROOT = ""
PROJECTS_ROUTE_PREFIX = "/projects"
PROJECTS_ROUTE_TAG = "projects"
PROJECT_ID_ROUTE = "/{project_id}"


# --- Ingestion stages (FR02) ---
class IngestionStage(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    INSPECTING = "inspecting"
    EXTRACTING_AUDIO = "extracting_audio"
    GENERATING_PROXY = "generating_proxy"
    ANALYSING = "analysing"
    COMPLETED = "completed"
    FAILED = "ingestion_failed"


def _csv(name: str, default: str) -> Tuple[str, ...]:
    raw = os.environ.get(name, default)
    return tuple(item.strip().lower() for item in raw.split(LIST_SEPARATOR) if item.strip())


@dataclass(frozen=True)
class Settings:
    media_root: Path
    rabbitmq_url: str
    allowed_source_domains: Tuple[str, ...]
    allowed_extensions: Tuple[str, ...]
    allowed_video_codecs: Tuple[str, ...]
    allowed_audio_codecs: Tuple[str, ...]
    max_duration_seconds: int
    max_upload_bytes: int
    subprocess_timeout_seconds: int


@lru_cache
def get_settings() -> Settings:
    """Load settings from environment variables (cached; call get_settings.cache_clear() after changing env)."""
    return Settings(
        media_root=Path(os.environ.get("MEDIA_ROOT", DEFAULT_MEDIA_ROOT)),
        rabbitmq_url=os.environ.get("RABBITMQ_URL", DEFAULT_RABBITMQ_URL),
        allowed_source_domains=_csv("ALLOWED_SOURCE_DOMAINS", DEFAULT_ALLOWED_SOURCE_DOMAINS),
        allowed_extensions=_csv("ALLOWED_EXTENSIONS", DEFAULT_ALLOWED_EXTENSIONS),
        allowed_video_codecs=_csv("ALLOWED_VIDEO_CODECS", DEFAULT_ALLOWED_VIDEO_CODECS),
        allowed_audio_codecs=_csv("ALLOWED_AUDIO_CODECS", DEFAULT_ALLOWED_AUDIO_CODECS),
        max_duration_seconds=int(os.environ.get("MAX_DURATION_SECONDS", DEFAULT_MAX_DURATION_SECONDS)),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)),
        subprocess_timeout_seconds=int(
            os.environ.get("SUBPROCESS_TIMEOUT_SECONDS", DEFAULT_SUBPROCESS_TIMEOUT_SECONDS)
        ),
    )
