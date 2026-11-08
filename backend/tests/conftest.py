import math
import os
import sys
from array import array
from fractions import Fraction
from pathlib import Path
from typing import Optional

import av
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

# Add the backend root to the Python path so the 'app' module can be found
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

SAMPLE_FPS = 25
SAMPLE_RATE = 48000
SAMPLE_LAYOUT = "stereo"
TONE_FREQUENCY = 440
TONE_AMPLITUDE = 0.5
# array typecode, full-scale value and converter for the sample formats the test encoders ask for
# (a trailing "p" in the format name only means planar).
SAMPLE_TYPES = {"flt": ("f", 1.0, float), "s16": ("h", 32767, int), "s32": ("i", 2**31 - 1, int)}
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg2://pei:pei@localhost:5432/pei_test")


def _tone_plane(first_sample: int, samples: int, interleaved_channels: int, format_name: str) -> bytes:
    """PCM bytes of a 440 Hz sine for one audio plane (planar formats have one channel per plane)."""
    typecode, full_scale, convert = SAMPLE_TYPES[format_name.rstrip("p")]
    values = array(typecode)
    for index in range(first_sample, first_sample + samples):
        value = TONE_AMPLITUDE * math.sin(2 * math.pi * TONE_FREQUENCY * index / SAMPLE_RATE)
        values.extend([convert(value * full_scale)] * interleaved_channels)
    return values.tobytes()


def _write_sample(
    path: Path,
    video_codec: str,
    audio_codec: Optional[str],
    width: int,
    height: int,
    seconds: int,
    tone: bool = False,
) -> Path:
    """Encode a short synthetic video (blank frames; silent audio, or a 440 Hz tone) with PyAV."""
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
                interleaved = 1 if frame.format.is_planar else len(frame.layout.channels)
                for plane in frame.planes:
                    data = _tone_plane(index * samples, samples, interleaved, audio_format) if tone else b""
                    plane.update(data.ljust(plane.buffer_size, b"\0"))
                frame.sample_rate, frame.pts = SAMPLE_RATE, index * samples
                container.mux(audio.encode(frame))
            container.mux(audio.encode(None))
    return path


@pytest.fixture
def make_sample(tmp_path):
    """Factory fixture: make_sample("mp4", "h264", "aac", tone=True) -> Path of a synthetic media file."""
    def factory(
        extension: str = "mp4",
        video_codec: str = "h264",
        audio_codec: Optional[str] = "aac",
        width: int = 320,
        height: int = 240,
        seconds: int = 2,
        tone: bool = False,
    ) -> Path:
        path = tmp_path / f"sample_{video_codec}_{audio_codec}.{extension}"
        return _write_sample(path, video_codec, audio_codec, width, height, seconds, tone)

    return factory


@pytest.fixture(scope="session")
def database_url():
    """Create the separate test database when needed, so tests never touch development data."""
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            query = text("SELECT 1 FROM pg_database WHERE datname = :name")
            if connection.scalar(query, {"name": url.database}) is None:
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL is not available; run 'docker compose up -d postgres' first. {exc}", pytrace=False)
    finally:
        admin.dispose()
    return TEST_DATABASE_URL


@pytest.fixture
def db(database_url):
    """A session on empty tables, recreated for each test."""
    from app.database import models  # noqa: F401 - registers the tables
    from app.database.base import Base

    engine = create_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()
