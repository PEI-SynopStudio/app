import math

import pytest

from app.services.video import ingestion as ingestion_module


@pytest.fixture
def captured_options(monkeypatch):
    """Replace YoutubeDL with a stub that records its options and downloads nothing."""
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def download(self, urls):
            pass

    monkeypatch.setattr(ingestion_module, "YoutubeDL", FakeYoutubeDL)
    return captured


@pytest.mark.parametrize("start, end, expected", [
    ("00:00:10", None, (10.0, math.inf)),
    (None, "00:00:30", (0.0, 30.0)),
    ("10", "30", (10.0, 30.0)),
])
def test_download_uses_the_requested_range(tmp_path, captured_options, start, end, expected):
    ingestion_module.download_youtube_video("https://youtu.be/x", tmp_path / "out.mp4", start, end)

    ranges = list(captured_options["download_ranges"]({"duration": 100, "id": "x"}, None))
    assert ranges == [{"start_time": expected[0], "end_time": expected[1]}]


def test_download_without_range_gets_the_whole_video(tmp_path, captured_options):
    ingestion_module.download_youtube_video("https://youtu.be/x", tmp_path / "out.mp4")

    assert "download_ranges" not in captured_options
