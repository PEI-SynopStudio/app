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


# --- yt-dlp (remote download) ---
YTDLP_MAX_HEIGHT = 1080
YTDLP_FORMAT_TEMPLATE = "bv*[height<={max_height}]+ba/b[height<={max_height}]"
YTDLP_FORMAT_SORT = ("vcodec:h264", "lang", "quality", "res", "fps", "hdr:12", "acodec:aac")
YTDLP_OUTPUT_CONTAINER = "mp4"
YTDLP_OUTPUT_TEMPLATE = "{stem}.%(ext)s"
YTDLP_REMUXER = "FFmpegVideoRemuxer"
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
ERROR_TIME_RANGE_INCOMPLETE = "Both start and end times are required to import a time range."
ERROR_INVALID_TIMECODE = "Invalid timecode: {value!r}"
ERROR_INVALID_TIME_RANGE = (
    "Invalid time range: start ({start:.0f} s) must be before end ({end:.0f} s), "
    "and end must not exceed the video duration ({duration:.0f} s)."
)

# --- Media inspection and audio normalization (PyAV) ---
STREAM_TYPE_AUDIO = "audio"
STREAM_TYPE_VIDEO = "video"
MEDIA_WRITE_MODE = "w"
AUDIO_SAMPLE_RATE = 16000
AUDIO_LAYOUT = "mono"
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

# --- Technical metadata (FR02 step 6) ---
METADATA_FILE = "metadata.json"
ASPECT_RATIO_FORMAT = "{numerator}:{denominator}"


class SourceType(str, Enum):
    UPLOAD = "upload"
    URL = "url"

# --- Proxy video (PyAV) ---
PROXY_MAX_HEIGHT = 720
EVEN_DIMENSION = 2
PROXY_CONTAINER = "mp4"
PROXY_MUXER_OPTIONS = {"movflags": "+faststart"}
PROXY_VIDEO_CODEC = "libx264"
PROXY_PIXEL_FORMAT = "yuv420p"
PROXY_VIDEO_OPTIONS = {"preset": "veryfast", "crf": "26"}
PROXY_AUDIO_CODEC = "aac"
PROXY_AUDIO_BITRATE = 128_000
PROXY_AUDIO_SAMPLE_FORMAT = "fltp"
PROXY_AUDIO_FRAME_SIZE = 1024
ERROR_NO_VIDEO_STREAM = "Video rejected: does not contain any video stream."
ERROR_PROXY_FAILED = "Failed to generate proxy video: {details}"


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
    )
