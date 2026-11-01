import sys
from fractions import Fraction
from pathlib import Path
from typing import Optional

import av
import pytest

# Add the backend root to the Python path so the 'app' module can be found
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

SAMPLE_FPS = 25
SAMPLE_RATE = 48000
SAMPLE_LAYOUT = "stereo"


def _write_sample(
    path: Path,
    video_codec: str,
    audio_codec: Optional[str],
    width: int,
    height: int,
    seconds: int,
) -> Path:
    """Encode a short synthetic video (blank frames, silent audio) with PyAV."""
    with av.open(str(path), "w") as container:
        # All streams must be added before the first packet is muxed.
        video = container.add_stream(video_codec, rate=SAMPLE_FPS)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        audio = container.add_stream(audio_codec, rate=SAMPLE_RATE, layout=SAMPLE_LAYOUT) if audio_codec else None

        for index in range(seconds * SAMPLE_FPS):
            frame = av.VideoFrame(width, height, "yuv420p")
            frame.pts, frame.time_base = index, Fraction(1, SAMPLE_FPS)
            container.mux(video.encode(frame))
        container.mux(video.encode(None))

        if audio is not None:
            audio_format = audio.codec_context.format.name
            samples = audio.codec_context.frame_size or 1024
            for index in range(seconds * SAMPLE_RATE // samples):
                frame = av.AudioFrame(format=audio_format, layout=SAMPLE_LAYOUT, samples=samples)
                for plane in frame.planes:
                    plane.update(bytes(plane.buffer_size))
                frame.sample_rate, frame.pts = SAMPLE_RATE, index * samples
                container.mux(audio.encode(frame))
            container.mux(audio.encode(None))
    return path


@pytest.fixture
def make_sample(tmp_path):
    """Factory fixture: make_sample("mp4", "h264", "aac") -> Path of a synthetic media file."""
    def factory(
        extension: str = "mp4",
        video_codec: str = "h264",
        audio_codec: Optional[str] = "aac",
        width: int = 320,
        height: int = 240,
        seconds: int = 2,
    ) -> Path:
        path = tmp_path / f"sample_{video_codec}_{audio_codec}.{extension}"
        return _write_sample(path, video_codec, audio_codec, width, height, seconds)

    return factory
