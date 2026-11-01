import shutil

import pytest

from app.services.video.ingestion import download_youtube_video, inspect_media

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"

# yt-dlp needs the ffmpeg executable to merge video + audio and to cut time ranges.
pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="the ffmpeg executable must be on PATH for yt-dlp"
)


def test_download_youtube_time_range(tmp_path):
    """Download a 20-second YouTube segment (needs network) and check it is a valid MP4 with audio."""
    video_path = download_youtube_video(
        url=SAMPLE_URL,
        output_path=tmp_path / "sample.mp4",
        start_time="00:01:07",
        end_time="00:01:27",
    )

    media = inspect_media(video_path)
    assert video_path.suffix == ".mp4"
    assert media.duration_seconds == pytest.approx(20, abs=2)
    assert media.streams_of("video")[0].height <= 1080
    assert media.streams_of("audio")
