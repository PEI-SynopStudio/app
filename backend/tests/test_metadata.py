import pytest

from app.core.config import SourceType
from app.services.video.ingestion import inspect_media
from app.services.video.metadata import build_technical_metadata


def test_build_technical_metadata(make_sample):
    media = inspect_media(make_sample("mkv", "hevc", "opus", width=640, height=360))

    metadata = build_technical_metadata(media, SourceType.UPLOAD, "lecture.mkv")

    assert metadata.source == "lecture.mkv"
    assert (metadata.width, metadata.height, metadata.aspect_ratio) == (640, 360, "16:9")
    assert metadata.frame_rate == pytest.approx(25)
    assert (metadata.video_codec, metadata.audio_codec) == ("hevc", "opus")
    assert metadata.sample_rate == 48000
    assert metadata.duration_seconds == pytest.approx(2, abs=0.1)
