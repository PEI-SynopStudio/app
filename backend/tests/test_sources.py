import pytest

from app.services.video import sources
from app.services.video.sources import probe_remote_video, validate_source_url, validate_time_range

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
PUBLIC_VIDEO = {
    "webpage_url": SAMPLE_URL,
    "title": "Sample",
    "duration": 600,
    "availability": "public",
    "live_status": "not_live",
    "extractor_key": "Youtube",
}


def fake_youtube_dl(info):
    """Replace yt-dlp with a stub whose extract_info returns the given metadata (no network)."""
    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            assert download is False
            return info

    return FakeYoutubeDL


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "http://m.youtube.com/watch?v=abc",
    "https://vimeo.com/123",
])
def test_validate_source_url_accepts_allowed_domains(url):
    assert validate_source_url(url) == url


@pytest.mark.parametrize("url", ["ftp://youtube.com/video", "youtube.com/watch?v=abc", "https://", "not a url"])
def test_validate_source_url_rejects_invalid_syntax(url):
    with pytest.raises(ValueError, match="Invalid URL"):
        validate_source_url(url)


@pytest.mark.parametrize("url", ["https://example.com/video.mp4", "https://evilyoutube.com/watch?v=abc"])
def test_validate_source_url_rejects_other_domains(url):
    with pytest.raises(ValueError, match="domain not allowed"):
        validate_source_url(url)


def test_probe_remote_video_accepts_public_video(monkeypatch):
    monkeypatch.setattr(sources, "YoutubeDL", fake_youtube_dl(PUBLIC_VIDEO))

    info = probe_remote_video(SAMPLE_URL)

    assert info.duration_seconds == 600
    assert info.availability == "public"


@pytest.mark.parametrize("changes, message", [
    ({"availability": "private"}, "only public or unlisted"),
    ({"live_status": "is_live"}, "live or upcoming"),
    ({"live_status": "is_upcoming"}, "live or upcoming"),
    ({"duration": None}, "could not be determined"),
    ({"duration": 5 * 3600}, "exceeds the limit"),
])
def test_probe_remote_video_rejects(monkeypatch, changes, message):
    monkeypatch.setattr(sources, "YoutubeDL", fake_youtube_dl({**PUBLIC_VIDEO, **changes}))

    with pytest.raises(ValueError, match=message):
        probe_remote_video(SAMPLE_URL)


def test_probe_remote_video_reads_real_metadata():
    """Needs network: reads YouTube metadata without downloading the video."""
    info = probe_remote_video(SAMPLE_URL)

    assert info.duration_seconds > 0
    assert info.availability in ("public", "unlisted", None)


def test_validate_time_range_is_optional():
    assert validate_time_range(None, None, 600) is None


@pytest.mark.parametrize("start, end, expected", [
    ("00:01:07", "00:01:27", (67, 87)),
    ("30", "90", (30, 90)),
    ("0", "00:10:00", (0, 600)),
    ("00:09:00", None, (540, 600)),
    (None, "00:01:00", (0, 60)),
])
def test_validate_time_range_parses_timecodes(start, end, expected):
    assert validate_time_range(start, end, 600) == expected


@pytest.mark.parametrize("start, end, message", [
    ("00:11:00", None, "Invalid time range"),
    ("abc", "00:01:00", "Invalid timecode"),
    ("00:02:00", "00:01:00", "Invalid time range"),
    ("00:01:00", "00:11:00", "Invalid time range"),
])
def test_validate_time_range_rejects(start, end, message):
    with pytest.raises(ValueError, match=message):
        validate_time_range(start, end, 600)
