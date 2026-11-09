import json
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
from in_memory_object_storage import InMemoryObjectStorage, UnavailableObjectStorage

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
def object_storage():
    return InMemoryObjectStorage()


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


def stage_upload(storage, project_id, sample, name="lecture.mp4", **params):
    """Copy a sample into the project's source directory, as the assembled upload would be."""
    shutil.copy(sample, storage.path(project_id, "source", name))
    return upload_request(project_id, name, **params)


def url_request(project_id, url=SAMPLE_URL, **params):
    return JobRequestMessage(job_id=uuid.uuid4(), project_id=project_id, parameters=IngestionParams(source_url=url, **params))


def run(storage, request, object_storage=None):
    events = []
    final = run_ingestion(storage, object_storage or InMemoryObjectStorage(), request, events.append)
    return final, events


def stored_keys(object_storage, project_id):
    return {key for owner, key in object_storage.objects if owner == project_id}


def working_dirs(storage, project_id):
    return [name for name in ("source", "audio", "proxy", "analysis") if (storage.project_dir(project_id) / name).exists()]


def steps(events):
    """The steps in order; a step can report its progress several times."""
    return list(dict.fromkeys(event.step for event in events if event.status == JobStatusEnum.PROCESSING))


def assert_failed(final, code):
    assert (final.status, final.error_code) == (JobStatusEnum.FAILED, code)


def test_upload_is_ingested(storage, object_storage, project_id, make_sample):
    final, events = run(storage, stage_upload(storage, project_id, make_sample(tone=True)), object_storage)

    assert final.status == JobStatusEnum.COMPLETED
    assert steps(events) == [JobStepProcessingEnum.INITIALIZING, *SUCCESS_STEPS]
    assert events[-1] == final
    assert stored_keys(object_storage, project_id) == {
        "source/lecture.mp4", "audio/audio.wav", "proxy/proxy.mp4", "analysis/waveform.json", "analysis/keyframes.json"
    }
    assert (final.output["source_type"], final.output["source"]) == ("upload", "lecture.mp4")
    assert (final.output["source_key"], final.output["proxy_key"], final.output["audio_key"]) == (
        "source/lecture.mp4", "proxy/proxy.mp4", "audio/audio.wav"
    )
    assert final.output["waveform_key"] == "analysis/waveform.json"
    assert final.output["keyframes_key"] == "analysis/keyframes.json"
    assert final.output["time_start_seconds"] is None
    assert json.loads(object_storage.objects[(project_id, "analysis/keyframes.json")])["times_seconds"][0] == 0
    waveform = json.loads(object_storage.objects[(project_id, "analysis/waveform.json")])
    assert len(waveform["peaks"]) == len(waveform["rms"]) == pytest.approx(20, abs=1)


def test_long_steps_report_progress_inside_the_step(storage, project_id, make_sample, monkeypatch):
    monkeypatch.setattr(ingestion_pipeline, "PROGRESS_EMIT_INTERVAL_SECONDS", 0)

    final, events = run(storage, stage_upload(storage, project_id, make_sample(tone=True)))

    assert final.status == JobStatusEnum.COMPLETED
    for step in (JobStepProcessingEnum.EXTRACTING_AUDIO, JobStepProcessingEnum.GENERATING_PROXY):
        progress = [event.step_progress for event in events if event.step == step]
        assert progress[0] == 0
        assert 0 < max(progress) <= 100


def test_progress_is_forwarded_at_most_once_per_interval(monkeypatch):
    clock = iter([0, 1, 3, 3.5, 6])
    monkeypatch.setattr(ingestion_pipeline.time, "monotonic", lambda: next(clock))
    sent = []

    forward = ingestion_pipeline._throttled(sent.append)
    for percent in (10, 20, 30, 40):
        forward(percent)

    assert sent == [20, 40]


def test_every_event_identifies_the_job_and_attempt(storage, project_id, make_sample):
    request = stage_upload(storage, project_id, make_sample(tone=True))

    _, events = run(storage, request)

    assert {(event.job_id, event.attempt) for event in events} == {(request.job_id, 1)}


def test_silent_upload_fails_before_proxy(storage, project_id, make_sample):
    final, events = run(storage, stage_upload(storage, project_id, make_sample()))

    assert_failed(final, JobErrorCodeEnum.SILENT_AUDIO)
    assert "silent" in final.error_message
    assert steps(events)[-1] == JobStepProcessingEnum.EXTRACTING_AUDIO
    assert not storage.path(project_id, "analysis", "waveform.json").exists()
    assert not storage.path(project_id, "analysis", "keyframes.json").exists()
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
    assert steps(events)[-1] == JobStepProcessingEnum.INSPECTING_MEDIA


@pytest.mark.parametrize("staged_file", [None, "missing.mp4", "../project.json", "/etc/passwd", "."])
def test_invalid_staged_file_fails(storage, project_id, staged_file):
    final, _ = run(storage, upload_request(project_id, staged_file))

    assert_failed(final, JobErrorCodeEnum.INVALID_SOURCE)


def test_upload_is_cut_to_the_requested_range(storage, object_storage, project_id, make_sample):
    sample = make_sample(seconds=10, tone=True, gop_size=50)

    final, _ = run(storage, stage_upload(storage, project_id, sample, time_start="3", time_end="7"), object_storage)

    assert final.status == JobStatusEnum.COMPLETED
    assert 0 <= final.output["time_start_seconds"] <= 3
    assert final.output["duration_seconds"] == pytest.approx(7 - final.output["time_start_seconds"], abs=0.5)
    assert [key for key in stored_keys(object_storage, project_id) if key.startswith("source/")] == ["source/lecture.mp4"]


def test_upload_can_be_cut_with_only_an_end(storage, project_id, make_sample):
    sample = make_sample(seconds=10, tone=True, gop_size=50)

    final, _ = run(storage, stage_upload(storage, project_id, sample, time_end="4"))

    assert final.status == JobStatusEnum.COMPLETED
    assert final.output["time_start_seconds"] == pytest.approx(0, abs=0.1)
    assert final.output["duration_seconds"] == pytest.approx(4, abs=0.5)


def test_upload_range_beyond_the_duration_fails(storage, project_id, make_sample):
    final, _ = run(storage, stage_upload(storage, project_id, make_sample(tone=True), time_start="20", time_end="30"))

    assert_failed(final, JobErrorCodeEnum.INVALID_SOURCE)
    assert "Invalid time range" in final.error_message


def test_chunks_are_assembled_by_the_job(storage, object_storage, project_id, make_sample):
    data = make_sample(tone=True).read_bytes()
    upload_id = uuid.uuid4()
    for index in range(2):
        part = data[:len(data) // 2] if index == 0 else data[len(data) // 2:]
        storage.path(project_id, "uploads", str(upload_id), "chunks", f"{index:06d}").write_bytes(part)
    request = upload_request(project_id, "assembled.mp4").model_copy(update={"upload_id": upload_id})

    final, _ = run(storage, request, object_storage)

    assert final.status == JobStatusEnum.COMPLETED
    assert object_storage.objects[(project_id, "source/assembled.mp4")] == data
    assert not (storage.project_dir(project_id) / "uploads" / str(upload_id)).exists()


def test_working_files_are_removed_but_other_uploads_stay(storage, project_id, make_sample):
    chunk = storage.path(project_id, "uploads", str(uuid.uuid4()), "chunks", "000000")
    chunk.write_bytes(b"chunk of another upload")

    final, _ = run(storage, stage_upload(storage, project_id, make_sample(tone=True)))

    assert final.status == JobStatusEnum.COMPLETED
    assert working_dirs(storage, project_id) == []
    assert chunk.exists()


def test_a_rejected_video_leaves_no_files(storage, object_storage, project_id, make_sample):
    final, _ = run(storage, stage_upload(storage, project_id, make_sample()), object_storage)

    assert_failed(final, JobErrorCodeEnum.SILENT_AUDIO)
    assert working_dirs(storage, project_id) == []
    assert object_storage.objects == {}


@pytest.mark.parametrize("tone, status", [(True, JobStatusEnum.COMPLETED), (False, JobStatusEnum.FAILED)])
def test_working_files_are_gone_before_the_final_event(storage, project_id, make_sample, tone, status):
    dirs_at_the_end = []

    def emit(event):
        if event.status == status:
            dirs_at_the_end.append(working_dirs(storage, project_id))

    run_ingestion(storage, InMemoryObjectStorage(), stage_upload(storage, project_id, make_sample(tone=tone)), emit)

    assert dirs_at_the_end == [[]]


def test_a_storage_failure_fails_the_job_and_removes_the_working_files(storage, project_id, make_sample):
    final, _ = run(storage, stage_upload(storage, project_id, make_sample(tone=True)), UnavailableObjectStorage())

    assert_failed(final, JobErrorCodeEnum.INTERNAL_ERROR)
    assert final.error_message == "The storage service is unavailable; please try again."
    assert working_dirs(storage, project_id) == []


def test_sending_the_results_reports_progress(storage, project_id, make_sample, monkeypatch):
    monkeypatch.setattr(ingestion_pipeline, "PROGRESS_EMIT_INTERVAL_SECONDS", 0)

    _, events = run(storage, stage_upload(storage, project_id, make_sample(tone=True)))

    progress = [event.step_progress for event in events if event.step == JobStepProcessingEnum.PERSISTING_RESULTS]
    assert progress == [0, 20, 40, 60, 80, 100]


def test_unexpected_error_is_recorded_and_raised(storage, project_id, make_sample, monkeypatch):
    def broken(*args):
        raise KeyError("bug")

    monkeypatch.setattr(ingestion_pipeline, "check_supported_formats", broken)
    events = []

    with pytest.raises(KeyError):
        run_ingestion(storage, InMemoryObjectStorage(), stage_upload(storage, project_id, make_sample(tone=True)), events.append)
    assert events[-1].error_code == JobErrorCodeEnum.INTERNAL_ERROR


def test_url_is_downloaded_and_ingested(storage, project_id, make_sample, monkeypatch):
    """URL flow with yt-dlp replaced by fakes (no network); test_download.py covers the real download."""
    sample = make_sample(tone=True)
    downloads = []

    def fake_probe(url):
        return RemoteVideoInfo(url=url, duration_seconds=600, availability="public")

    def fake_download(url, output_path, start_time, end_time, on_progress):
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
