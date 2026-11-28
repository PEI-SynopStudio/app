import math
import os
import sys
from array import array
from fractions import Fraction
from itertools import accumulate, cycle, islice
from pathlib import Path
from typing import Optional, Sequence

import av
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

# Add the backend root to the Python path so the 'app' module can be found
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: needs a real LLM server; runs only when TEST_LLM_PROFILE is set")

SAMPLE_FPS = 25
SAMPLE_RATE = 48000
SAMPLE_LAYOUT = "stereo"
TONE_FREQUENCY = 440
TONE_AMPLITUDE = 0.5
# array typecode, full-scale value and converter for the sample formats the test encoders ask for
# (a trailing "p" in the format name only means planar).
SAMPLE_TYPES = {"flt": ("f", 1.0, float), "s16": ("h", 32767, int), "s32": ("i", 2**31 - 1, int)}
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg2://pei:pei@localhost:5433/pei_test")

# Tests also run inside the backend container, which carries the deployment's HTTPS settings. The test client speaks
# plain http://testserver, so the config.py defaults apply instead (Secure cookies would never be sent back).
for _name in ("SESSION_COOKIE_SECURE", "APP_PUBLIC_URL"):
    os.environ.pop(_name, None)


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
    frame_times_ms: Optional[Sequence[int]] = None,
    gop_size: Optional[int] = None,
) -> Path:
    """Encode a short synthetic video (blank frames; silent audio, or a 440 Hz tone) with PyAV.

    Frames come at a constant rate, or at the exact `frame_times_ms` when given.
    `gop_size` is the distance between keyframes, in frames.
    """
    with av.open(str(path), "w") as container:
        # All streams must be added before the first packet is muxed.
        video = container.add_stream(video_codec, rate=SAMPLE_FPS)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        if gop_size is not None:
            video.codec_context.gop_size = gop_size
        audio = container.add_stream(audio_codec, rate=SAMPLE_RATE, layout=SAMPLE_LAYOUT) if audio_codec else None

        time_base = Fraction(1, 1000) if frame_times_ms is not None else Fraction(1, SAMPLE_FPS)
        video.codec_context.time_base = time_base
        for pts in frame_times_ms if frame_times_ms is not None else range(seconds * SAMPLE_FPS):
            frame = av.VideoFrame(width, height, "yuv420p")
            frame.pts, frame.time_base = pts, time_base
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
        frame_times_ms: Optional[Sequence[int]] = None,
        gop_size: Optional[int] = None,
    ) -> Path:
        path = tmp_path / f"sample_{video_codec}_{audio_codec}.{extension}"
        return _write_sample(path, video_codec, audio_codec, width, height, seconds, tone, frame_times_ms, gop_size)

    return factory


@pytest.fixture
def vfr_frame_times():
    """Frame times in ms of a clip of about 2 s whose intervals keep changing."""
    return list(accumulate(islice(cycle((20, 40, 40, 66, 100)), 37), initial=0))


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
def session_factory(database_url):
    """Sessions on empty tables, recreated for each test."""
    from app.database import models  # noqa: F401 - registers the tables
    from app.database.base import Base

    engine = create_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def db_override(session_factory):
    """Point the API's get_db dependency to the test database; the client fixtures clear it."""
    from app.database.session import get_db
    from app.main import app

    def override():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override


def add_user(session_factory, subject="subject-1", email="owner@example.com", name="Owner"):
    """An account as the first Keycloak sign-in creates it."""
    from app.services.auth.auth import provision_user
    from fake_identity_provider import make_claims

    with session_factory() as session:
        return provision_user(session, make_claims(subject=subject, email=email, name=name))


@pytest.fixture
def user(session_factory):
    """The account the API clients of the tests are signed in as."""
    return add_user(session_factory)


def sign_in(client, session_factory, user, authenticated_at=None):
    """Give the test client a session cookie of `user`, as a browser has right after signing in at Keycloak."""
    from app.core.config import SESSION_COOKIE_NAME
    from app.database.base import utc_now
    from app.services.auth.auth import create_session

    with session_factory() as session:
        new = create_session(
            session, user, idp_session_id="idp-session-1", authenticated_at=authenticated_at or utc_now()
        )
        client.cookies.set(SESSION_COOKIE_NAME, new.token)
    return client


@pytest.fixture
def identity_provider():
    """Keycloak replaced by a fake for the API; the client fixtures clear the override."""
    from app.main import app
    from app.services.auth.keycloak import get_identity_provider
    from fake_identity_provider import FakeIdentityProvider

    fake = FakeIdentityProvider()
    app.dependency_overrides[get_identity_provider] = lambda: fake
    return fake


@pytest.fixture
def queues(monkeypatch):
    """Exchanges and queues of this test only, removed at the end; skipped without a broker."""
    import asyncio
    import uuid

    import aio_pika

    from app.services.workflow import event_consumer, rabbitmq as rabbitmq_module
    from test_rabbitmq import TEST_RABBITMQ_URL, broker_is_running

    if not broker_is_running():
        pytest.skip("RabbitMQ is not available; run 'docker compose up -d rabbitmq' first")
    prefix = f"test-{uuid.uuid4().hex}"
    names = {
        "JOBS_EXCHANGE": f"{prefix}-jobs",
        "JOBS_QUEUE_FORMAT": f"{prefix}-jobs.{{job_type}}",
        "JOB_EVENTS_EXCHANGE": f"{prefix}-events",
        "JOB_EVENTS_QUEUE": f"{prefix}-events.queue",
        "DEAD_LETTER_EXCHANGE": f"{prefix}-dlx",
        "DEAD_LETTER_QUEUE": f"{prefix}-dlq",
        "MEDIA_EVENTS_EXCHANGE": f"{prefix}-media",
        "MEDIA_INGESTED_QUEUE": f"{prefix}-media.ingested",
    }
    for constant, value in names.items():
        monkeypatch.setattr(rabbitmq_module, constant, value)
    monkeypatch.setattr(event_consumer, "EVENT_CONSUMER_RETRY_SECONDS", 0.05)
    yield names

    async def remove():
        connection = await aio_pika.connect(TEST_RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            for queue in (
                names["JOBS_QUEUE_FORMAT"].format(job_type="ingestion"),
                names["JOB_EVENTS_QUEUE"],
                names["MEDIA_INGESTED_QUEUE"],
                names["DEAD_LETTER_QUEUE"],
            ):
                await channel.queue_delete(queue)
            for exchange in (
                names["JOBS_EXCHANGE"],
                names["JOB_EVENTS_EXCHANGE"],
                names["MEDIA_EVENTS_EXCHANGE"],
                names["DEAD_LETTER_EXCHANGE"],
            ):
                await channel.exchange_delete(exchange)

    asyncio.run(remove())
