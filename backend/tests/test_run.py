import shutil
from pathlib import Path

import pytest

from app.services.video.ingestion import (
    download_youtube_video,
    inspect_media,
    extract_normalized_audio,
    generate_proxy_video,
)

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"

requires_media_tools = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "yt-dlp")),
    reason="ffmpeg, ffprobe and yt-dlp must be on PATH",
)


def stream_types(probe_data: dict) -> list:
    return [s.get("codec_type") for s in probe_data.get("streams", [])]


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    """Download a 20-second YouTube segment once for all tests in this module (needs network)."""
    video_path = tmp_path_factory.mktemp("media") / "sample.mp4"
    download_youtube_video(
        url=SAMPLE_URL,
        output_path=video_path,
        start_time="00:01:07",
        end_time="00:01:27",
    )
    assert video_path.stat().st_size > 0, "Downloaded video is empty"
    return video_path


def test_inspect_media_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        inspect_media(tmp_path / "missing.mp4")


@requires_media_tools
def test_inspect_media_detects_audio(sample_video):
    info = inspect_media(sample_video)
    assert "audio" in stream_types(info)
    assert float(info["format"]["duration"]) > 0


@requires_media_tools
def test_extract_normalized_audio(sample_video, tmp_path):
    audio_path = extract_normalized_audio(sample_video, tmp_path / "normalized_audio.wav")
    audio = inspect_media(audio_path)["streams"][0]
    assert audio["codec_name"] == "pcm_s16le"
    assert audio["sample_rate"] == "16000"
    assert audio["channels"] == 1


@requires_media_tools
def test_generate_proxy_video(sample_video, tmp_path):
    proxy_path = generate_proxy_video(sample_video, tmp_path / "proxy_720p.mp4")
    assert proxy_path.stat().st_size > 0
    assert {"video", "audio"} <= set(stream_types(inspect_media(proxy_path)))
