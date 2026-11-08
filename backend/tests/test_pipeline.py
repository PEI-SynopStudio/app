import shutil
import uuid

import pytest

from app.core.config import IngestionStage, SourceType, get_settings
from app.services.storage.local import LocalStorage
from app.services.video import sources as sources_module
from app.services.video.metadata import get_technical_metadata
from app.services.video.sources import RemoteVideoInfo
from app.services.workflow import ingestion_pipeline
from app.services.workflow.ingestion_pipeline import IngestionJob, run_ingestion
from app.services.workflow.status import get_status

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
SUCCESS_STAGES = [
    IngestionStage.INSPECTING,
    IngestionStage.EXTRACTING_AUDIO,
    IngestionStage.GENERATING_PROXY,
    IngestionStage.ANALYSING,
    IngestionStage.COMPLETED,
]


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def project_id():
    return str(uuid.uuid4())


def stage_upload(storage, project_id, sample, name="lecture.mp4"):
    """Copy a sample into the project's source directory, as the upload API will do."""
    shutil.copy(sample, storage.path(project_id, "source", name))
    return IngestionJob(project_id=project_id, source_type=SourceType.UPLOAD, source=name, staged_file=name)


def run(storage, job):
    progress = []
    status = run_ingestion(storage, job, on_progress=progress.append)
    return status, [update.stage for update in progress]


def test_upload_is_ingested(storage, project_id, make_sample):
    job = stage_upload(storage, project_id, make_sample(tone=True))

    status, stages = run(storage, job)

    assert status.stage == IngestionStage.COMPLETED
    assert stages == SUCCESS_STAGES
    assert get_status(storage, project_id) == status
    assert storage.path(project_id, "audio", "audio.wav").is_file()
    assert storage.path(project_id, "proxy", "proxy.mp4").is_file()
    metadata = get_technical_metadata(storage, project_id)
    assert (metadata.source_type, metadata.source) == (SourceType.UPLOAD, "lecture.mp4")


def test_silent_upload_fails_before_proxy(storage, project_id, make_sample):
    job = stage_upload(storage, project_id, make_sample())

    status, stages = run(storage, job)

    assert status.stage == IngestionStage.FAILED
    assert status.error.code == "silent_audio"
    assert "silent" in status.error.message
    assert stages[-2:] == [IngestionStage.EXTRACTING_AUDIO, IngestionStage.FAILED]
    assert not storage.path(project_id, "proxy", "proxy.mp4").exists()


def test_unsupported_codec_fails(storage, project_id, make_sample):
    job = stage_upload(storage, project_id, make_sample("mkv", "mpeg4", "aac", tone=True), "lecture.mkv")

    status, _ = run(storage, job)

    assert (status.stage, status.error.code) == (IngestionStage.FAILED, "unsupported_format")
    assert "video codec" in status.error.message


def test_upload_longer_than_limit_fails(storage, project_id, make_sample, monkeypatch):
    monkeypatch.setenv("MAX_DURATION_SECONDS", "1")
    get_settings.cache_clear()
    try:
        status, _ = run(storage, stage_upload(storage, project_id, make_sample(tone=True)))
    finally:
        get_settings.cache_clear()

    assert "exceeds the limit" in status.error.message
    assert status.error.code == "duration_limit_exceeded"


def test_corrupted_upload_fails_as_processing_error(storage, project_id, tmp_path):
    corrupted = tmp_path / "corrupted.mp4"
    corrupted.write_bytes(b"not a video" * 100)

    status, _ = run(storage, stage_upload(storage, project_id, corrupted))

    assert (status.stage, status.error.code) == (IngestionStage.FAILED, "corrupted_media")


@pytest.mark.parametrize("staged_file", [None, "missing.mp4", "../project.json", "/etc/passwd", "."])
def test_invalid_staged_file_fails(storage, project_id, staged_file):
    job = IngestionJob(
        project_id=project_id, source_type=SourceType.UPLOAD, source="x.mp4", staged_file=staged_file
    )

    status, _ = run(storage, job)

    assert (status.stage, status.error.code) == (IngestionStage.FAILED, "invalid_source")


def test_upload_time_range_is_not_supported_yet(storage, project_id, make_sample):
    job = stage_upload(storage, project_id, make_sample(tone=True))
    job.start_time, job.end_time = "0", "1"

    status, _ = run(storage, job)

    assert "not supported for uploaded files" in status.error.message


def test_unexpected_error_is_recorded_and_raised(storage, project_id, make_sample, monkeypatch):
    def broken(*args):
        raise KeyError("bug")

    monkeypatch.setattr(ingestion_pipeline, "check_supported_formats", broken)

    with pytest.raises(KeyError):
        run_ingestion(storage, stage_upload(storage, project_id, make_sample(tone=True)))
    assert get_status(storage, project_id).error.code == "internal_error"


def test_url_is_downloaded_and_ingested(storage, project_id, make_sample, monkeypatch):
    """URL flow with yt-dlp replaced by fakes (no network); test_download.py covers the real download."""
    sample = make_sample(tone=True)
    downloads = []

    def fake_probe(url):
        return RemoteVideoInfo(url=url, duration_seconds=600, availability="public")

    def fake_download(url, output_path, start_time, end_time):
        downloads.append((url, start_time, end_time))
        return shutil.copy(sample, output_path)

    monkeypatch.setattr(ingestion_pipeline, "probe_remote_video", fake_probe)
    monkeypatch.setattr(ingestion_pipeline, "download_youtube_video", fake_download)
    job = IngestionJob(
        project_id=project_id, source_type=SourceType.URL, source=SAMPLE_URL, start_time="10", end_time="30"
    )

    status, stages = run(storage, job)

    assert status.stage == IngestionStage.COMPLETED
    assert stages == [IngestionStage.DOWNLOADING, *SUCCESS_STAGES]
    assert downloads == [(SAMPLE_URL, "10", "30")]
    assert get_technical_metadata(storage, project_id).source == SAMPLE_URL


def test_url_from_other_domain_fails(storage, project_id):
    # The real probe rejects the domain before any network call.
    job = IngestionJob(project_id=project_id, source_type=SourceType.URL, source="https://example.com/video.mp4")

    status, _ = run(storage, job)

    assert (status.stage, status.error.code) == (IngestionStage.FAILED, "invalid_source")
    assert "domain not allowed" in status.error.message


def test_url_time_range_beyond_duration_fails(storage, project_id, monkeypatch):
    monkeypatch.setattr(
        ingestion_pipeline, "probe_remote_video", lambda url: RemoteVideoInfo(url=url, duration_seconds=600)
    )
    job = IngestionJob(
        project_id=project_id, source_type=SourceType.URL, source=SAMPLE_URL,
        start_time="00:20:00", end_time="00:30:00",
    )

    status, _ = run(storage, job)

    assert (status.stage, status.error.code) == (IngestionStage.FAILED, "invalid_source")
    assert "Invalid time range" in status.error.message


def test_new_run_clears_previous_metadata(storage, project_id, make_sample):
    run(storage, stage_upload(storage, project_id, make_sample(tone=True)))
    assert get_technical_metadata(storage, project_id) is not None

    status, _ = run(storage, IngestionJob(
        project_id=project_id, source_type=SourceType.URL, source="https://example.com/video.mp4"
    ))

    assert status.stage == IngestionStage.FAILED
    assert get_technical_metadata(storage, project_id) is None


def test_video_without_audio_track_is_reported(storage, project_id, make_sample):
    job = stage_upload(storage, project_id, make_sample(audio_codec=None))

    status, _ = run(storage, job)

    assert (status.stage, status.error.code) == (IngestionStage.FAILED, "no_audio_track")


def test_private_video_is_reported_as_unavailable(storage, project_id, monkeypatch):
    class PrivateVideo:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"availability": "private", "duration": 600}

    monkeypatch.setattr(sources_module, "YoutubeDL", PrivateVideo)

    status, _ = run(storage, IngestionJob(project_id=project_id, source_type=SourceType.URL, source=SAMPLE_URL))

    assert (status.stage, status.error.code) == (IngestionStage.FAILED, "source_unavailable")
