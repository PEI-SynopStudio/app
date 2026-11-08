from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from app.core.config import (
    STREAM_TYPE_AUDIO,
    STREAM_TYPE_VIDEO,
    SourceType,
)
from app.services.video.ingestion import MediaInfo


class TechnicalMetadata(BaseModel):
    source_type: SourceType
    source: str
    container: str
    duration_seconds: Optional[float] = None
    size_bytes: int
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[str] = None
    frame_rate: Optional[float] = None
    is_vfr: Optional[bool] = None
    video_codec: str
    audio_codec: str
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    created_at: datetime


class IngestionOutput(TechnicalMetadata):
    """What a finished ingestion reports in its completed event; keys are relative to the project."""
    source_key: str
    proxy_key: str
    audio_key: str


# Collect the technical metadata of the original source from its inspection result.
# Source: MS2 FR02 – Step 6 (runtime, dimensions, aspect ratio, frame rate, sample rate, source URL or file name).
def build_technical_metadata(media: MediaInfo, is_vfr: bool, source_type: SourceType, source: str) -> TechnicalMetadata:
    """Build the metadata record; `source` is the original URL or the uploaded file name."""
    video = media.streams_of(STREAM_TYPE_VIDEO)[0]
    audio = media.streams_of(STREAM_TYPE_AUDIO)[0]
    return TechnicalMetadata(
        source_type=source_type,
        source=source,
        container=media.format_name,
        duration_seconds=media.duration_seconds,
        size_bytes=media.size_bytes,
        width=video.width,
        height=video.height,
        aspect_ratio=video.aspect_ratio,
        frame_rate=video.frame_rate,
        is_vfr=is_vfr,
        video_codec=video.codec_name,
        audio_codec=audio.codec_name,
        sample_rate=audio.sample_rate,
        channels=audio.channels,
        created_at=datetime.now(timezone.utc),
    )
