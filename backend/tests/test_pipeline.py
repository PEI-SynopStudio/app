import shutil
import uuid

import pytest

from app.core.config import JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum, get_settings
from app.schemas.job import IngestionParams, JobRequestMessage
from app.services.storage.local import LocalStorage
from app.services.video import sources as sources_module
from app.services.video.sources import RemoteVideoInfo
from app.services.workflow import ingestion_pipeline
from app.services.workflow.ingestion_pipeline import run_ingestion

SAMPLE_URL = "https://www.youtube.com/watch?v=9bZkp7q19f0"
SUCCESS_STEPS = [
    JobStepProcessingEnum.INSPECTING_MEDIA,
    JobStepProcessingEnum.EXTRACTING_AUDIO,
    JobStepProcessingEnum.GENERATING_PROXY,
    JobStepProcessingEnum.PERSISTING_RESULTS,
]


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def project_id():
    return str(uuid.uuid4())


def upload_request(project_id, staged_file="lecture.mp4", **params):
    return JobRequestMessage(
        job_id=uuid.uuid4(),
        project_id=project_id,
        parameters=IngestionParams(media_id=uuid.uuid4(), **params),
        staged_file=staged_file,
        file_name="lecture.mp4",
    )


def stage_upload(storage, project_id, sample, name="lecture.mp4"):
    """Copy a sample into the project's source directory, as the assembled upload would be."""
    shutil.copy(sample, storage.path(project_id, "source", name))
    return upload_request(project_id, name)


def url_request(project_id, url=SAMPLE_URL, **params):
    return JobRequestMessage(job_id=uuid.uuid4(), project_id=project_id, parameters=IngestionParams(source_url=url, **params))


def run(storage, request):
    events = []
    final = run_ingestion(storage, request, events.append)
    return final, events


def steps(events):
    return [event.step for event in events if event.status == JobStatusEnum.PROCESSING]


def assert_failed(final, code):
    assert (final.status, final.error_code) == (JobStatusEnum.FAILED, code)


def test_upload_is_ingested(storage, project_id, make_sample):
    final, events = run(storage, stage_upload(storage, project_id, make_sample(tone=True)))

    assert final.status == JobStatusEnum.COMPLETED
    assert steps(events) == [JobStepProcessingEnum.INITIALIZING, *SUCCESS_STEPS]
    assert events[-1] == final
    assert storage.path(project_id, "audio", "audio.wav").is_file()
    assert storage.path(project_id, "proxy", "proxy.mp4").is_file()
    assert (final.output["source_type"], final.output["source"]) == ("upload", "lecture.mp4")
    assert (final.output["source_key"], final.output["proxy_key"], final.output["audio_key"]) == (
        "source/lecture.mp4", "proxy/proxy.mp4", "audio/audio.wav"
    )


def test_every_event_identifies_the_job_and_attempt(storage, project_id, make_sample):
    request = stage_upload(storage, project_id, make_sample(tone=True))

    _, events = run(storage, request)

    assert {(event.job_id, event.attempt) for event in events} == {(request.job_id, 1)}


def test_silent_upload_fails_before_proxy(storage, project_id, make_sample):
    final, events = run(storage, stage_upload(storage, project_id, make_sample()))

    assert_failed(final, JobErrorCodeEnum.SILENT_AUDIO)
    assert "silent" in final.error_message
    assert steps(events)[-1] == JobStepProcessingEnum.EXTRACTING_AUDIO
    assert not storage.path(project_id, "proxy", "proxy.mp4").exists()


def test_unsupported_codec_fails(storage, project_id, make_sample):
    sample = make_sample("mkv", "mpeg4", "aac", tone=True)

    final, _ = run(storage, stage_upload(storage, project_id, sample, "lecture.mkv"))

    assert_failed(final, JobErrorCodeEnum.UNSUPPORTED_FORMAT)
    assert "video codec" in final.error_message


def test_upload_longer_than_limit_fails(storage, project_id, make_sample, monkeypatch):
    monkeypatch.setenv("MAX_DURATION_SECONDS", "1")
    get_settings.cache_clear()
    try:
        final, _ = run(storage, stage_upload(storage, project_id, make_sample(tone=True)))
    finally:
        get_settings.cache_clear()

    assert_failed(final, JobErrorCodeEnum.DURATION_LIMIT_EXCEEDED)
    assert "exceeds the limit" in final.error_message


def test_corrupted_upload_fails_as_processing_error(storage, project_id, tmp_path):
    corrupted = tmp_path / "corrupted.mp4"
    corrupted.write_bytes(b"not a video" * 100)

    final, _ = run(storage, stage_upload(storage, project_id, corrupted))

    assert_failed(final, JobErrorCodeEnum.CORRUPTED_MEDIA)


def test_variable_frame_rate_upload_is_ingested_and_flagged(storage, project_id, make_sample, vfr_frame_times):
    sample = make_sample(tone=True, frame_times_ms=vfr_frame_times)

    final, _ = run(storage, stage_upload(storage, project_id, sample))

    assert final.status == JobStatusEnum.COMPLETED
    assert final.output["is_vfr"] is True


def test_avi_upload_with_reordered_frames_is_ingested(storage, project_id, make_sample):
    sample = make_sample("avi", "h264", "mp3", tone=True)

    final, _ = run(storage, stage_upload(storage, project_id, sample, "lecture.avi"))

    assert final.status == JobStatusEnum.COMPLETED
    assert final.output["is_vfr"] is False


def test_constant_frame_rate_upload_is_not_flagged(storage, project_id, make_sample):
    final, _ = run(storage, stage_upload(storage, project_id, make_sample(tone=True)))

    assert final.output["is_vfr"] is False


def test_truncated_upload_fails_before_audio_extraction(storage, project_id, make_sample):
    sample = make_sample("mkv", tone=True, seconds=8)
    sample.write_bytes(sample.read_bytes()[: sample.stat().st_size // 2])

    final, events = run(storage, stage_upload(storage, project_id, sample, "lecture.mkv"))

    assert_failed(final, JobErrorCodeEnum.CORRUPTED_MEDIA)
    assert "incomplete" in final.error_message
    assert steps(events)[-1] == JobStepProcessingEnum.INSPECTING_MEDIA


@pytest.mark.parametrize("staged_file", [None, "missing.mp4", "../project.json", "/etc/passwd", "."])
def test_invalid_staged_file_fails(storage, project_id, staged_file):
    final, _ = run(storage, upload_request(project_id, staged_file))

    assert_failed(final, JobErrorCodeEnum.INVALID_SOURCE)


def test_upload_time_range_is_not_supported_yet(storage, project_id):
    final, _ = run(storage, upload_request(project_id, time_start="0", time_end="1"))

    assert "not supported for uploaded files" in final.error_message


def test_chunks_are_assembled_by_the_job(storage, project_id, make_sample):
    data = make_sample(tone=True).read_bytes()
    upload_id = uuid.uuid4()
    for index in range(2):
        part = data[:len(data) // 2] if index == 0 else data[len(data) // 2:]
        storage.path(project_id, "uploads", str(upload_id), "chunks", f"{index:06d}").write_bytes(part)
    request = upload_request(project_id, "assembled.mp4").model_copy(update={"upload_id": upload_id})

    final, _ = run(storage, request)

    assert final.status == JobStatusEnum.COMPLETED
    assert storage.path(project_id, "source", "assembled.mp4").read_bytes() == data
    assert not (storage.project_dir(project_id) / "uploads" / str(upload_id)).exists()


def test_unexpected_error_is_recorded_and_raised(storage, project_id, make_sample, monkeypatch):
    def broken(*args):
        raise KeyError("bug")

    monkeypatch.setattr(ingestion_pipeline, "check_supported_formats", broken)
    events = []

    with pytest.raises(KeyError):
        run_ingestion(storage, stage_upload(storage, project_id, make_sample(tone=True)), events.append)
    assert events[-1].error_code == JobErrorCodeEnum.INTERNAL_ERROR


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

    final, events = run(storage, url_request(project_id, time_start="10", time_end="30"))

    assert final.status == JobStatusEnum.COMPLETED
    assert steps(events) == [
        JobStepProcessingEnum.INITIALIZING, JobStepProcessingEnum.DOWNLOADING_MEDIA, *SUCCESS_STEPS
    ]
    assert downloads == [(SAMPLE_URL, "10", "30")]
    assert (final.output["source"], final.output["source_key"]) == (SAMPLE_URL, "source/original.mp4")


def test_url_from_other_domain_fails(storage, project_id):
    # The real probe rejects the domain before any network call.
    final, _ = run(storage, url_request(project_id, "https://example.com/video.mp4"))

    assert_failed(final, JobErrorCodeEnum.INVALID_SOURCE)
    assert "domain not allowed" in final.error_message


def test_url_time_range_beyond_duration_fails(storage, project_id, monkeypatch):
    monkeypatch.setattr(
        ingestion_pipeline, "probe_remote_video", lambda url: RemoteVideoInfo(url=url, duration_seconds=600)
    )

    final, _ = run(storage, url_request(project_id, time_start="00:20:00", time_end="00:30:00"))

    assert_failed(final, JobErrorCodeEnum.INVALID_SOURCE)
    assert "Invalid time range" in final.error_message


def test_video_without_audio_track_is_reported(storage, project_id, make_sample):
    final, _ = run(storage, stage_upload(storage, project_id, make_sample(audio_codec=None)))

    assert_failed(final, JobErrorCodeEnum.NO_AUDIO_TRACK)


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

    final, _ = run(storage, url_request(project_id))

    assert_failed(final, JobErrorCodeEnum.SOURCE_UNAVAILABLE)
