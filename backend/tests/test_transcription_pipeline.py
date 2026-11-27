import json
import uuid

import pytest

from app.core.config import JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum
from app.schemas.job import JobRequestMessage, TranscriptionParams
from app.schemas.transcript import TranscriptDocument
from app.services.speech.alignment import AlignedWord
from app.services.speech.models import LoadedAligner, LoadedWhisper
from app.services.storage.local import LocalStorage
from app.services.workflow import transcription_pipeline
from app.services.workflow.transcription_pipeline import SpeechModels, run_transcription
from in_memory_object_storage import InMemoryObjectStorage, UnavailableObjectStorage
from test_speech_audio import write_wav
from test_speech_transcription import FakeWhisper, spoken

AUDIO_KEY = "audio/audio.wav"
STEPS = [
    JobStepProcessingEnum.INITIALIZING,
    JobStepProcessingEnum.TRANSCRIBING,
    JobStepProcessingEnum.PERSISTING_RESULTS,
    JobStepProcessingEnum.CLEANING_UP,
]


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "media")


@pytest.fixture
def project_id():
    return str(uuid.uuid4())


@pytest.fixture
def object_storage(tmp_path, project_id):
    storage = InMemoryObjectStorage()
    wav = tmp_path / "audio.wav"
    write_wav(wav, [(3, 0.5)])
    storage.put_file(project_id, AUDIO_KEY, wav)
    return storage


@pytest.fixture(autouse=True)
def aligned_as_whisper(monkeypatch):
    """wav2vec2 replaced by a fake that keeps faster-whisper's times."""

    def fake_align(aligner, samples, segment):
        return tuple(AlignedWord(w.text, w.start, w.end, w.probability, True) for w in segment.words)

    monkeypatch.setattr(transcription_pipeline, "align_segment", fake_align)


def models(*segments, aligner_error=None):
    def aligner(language):
        if aligner_error:
            raise aligner_error
        return LoadedAligner("wav2vec2-pt", "b" * 40, None, None)

    return SpeechModels(LoadedWhisper("large-v3-turbo", "a" * 40, FakeWhisper(segments)), aligner)


def request(project_id, audio_key=AUDIO_KEY, offset=0.0):
    return JobRequestMessage(
        job_id=uuid.uuid4(),
        project_id=project_id,
        parameters=TranscriptionParams(media_id=uuid.uuid4(), language="pt-PT"),
        audio_key=audio_key,
        time_offset_seconds=offset,
    )


def run(storage, object_storage, speech_models, job):
    events = []
    final = run_transcription(storage, object_storage, speech_models, job, events.append)
    return final, events


def test_transcript_is_stored_and_reported(storage, object_storage, project_id):
    job = request(project_id, offset=12.5)

    final, events = run(storage, object_storage, models(spoken(" Bom dia.", 0.5, 1.5)), job)

    assert final.status == JobStatusEnum.COMPLETED, final.error_message
    assert [event.step for event in events[:-1] if event.step_progress == 0] == STEPS
    assert final.output["transcript_key"] == "transcript/transcript.json"
    assert (final.output["model_revision"], final.output["alignment_model_name"]) == ("a" * 40, "wav2vec2-pt")
    assert (final.output["word_count"], final.output["aligned_word_count"]) == (1, 1)
    assert final.output["parameters"]["vad_filter"] is True
    document = TranscriptDocument.model_validate(json.loads(object_storage.objects[(project_id, "transcript/transcript.json")]))
    assert (document.language, document.segments[0].text, document.segments[0].start) == ("pt-PT", "Bom dia.", 13.0)


def test_scratch_files_are_removed_and_other_job_files_are_kept(storage, object_storage, project_id):
    ingestion_file = storage.path(project_id, "audio", "audio.wav")
    ingestion_file.write_bytes(b"ingestion")
    job = request(project_id)

    run(storage, object_storage, models(spoken(" Olá.", 0.0, 1.0)), job)

    assert not (storage.project_dir(project_id) / "speech" / str(job.job_id)).exists()
    assert ingestion_file.read_bytes() == b"ingestion"


def test_audio_without_speech_fails_with_its_code(storage, object_storage, project_id):
    job = request(project_id)

    final, _ = run(storage, object_storage, models(), job)

    assert (final.status, final.error_code) == (JobStatusEnum.FAILED, JobErrorCodeEnum.NO_SPEECH_DETECTED)
    assert (project_id, "transcript/transcript.json") not in object_storage.objects
    assert not (storage.project_dir(project_id) / "speech" / str(job.job_id)).exists()


def test_job_without_audio_key_is_an_invalid_source(storage, object_storage, project_id):
    final, _ = run(storage, object_storage, models(), request(project_id, audio_key=None))

    assert final.error_code == JobErrorCodeEnum.INVALID_SOURCE


def test_model_that_cannot_load_fails_as_unavailable(storage, object_storage, project_id):
    final, _ = run(storage, object_storage, models(aligner_error=RuntimeError("no weights")), request(project_id))

    assert (final.error_code, final.error_message) == (JobErrorCodeEnum.MODEL_UNAVAILABLE, "no weights")


def test_storage_outage_fails_as_internal_error(storage, project_id):
    final, _ = run(storage, UnavailableObjectStorage(), models(), request(project_id))

    assert final.error_code == JobErrorCodeEnum.INTERNAL_ERROR


def test_unexpected_error_is_reported_and_raised(storage, object_storage, project_id, monkeypatch):
    def broken(*args):
        raise KeyError("bug")

    monkeypatch.setattr(transcription_pipeline, "build_segment", broken)
    events = []

    with pytest.raises(KeyError):
        run_transcription(storage, object_storage, models(spoken(" Olá.", 0.0, 1.0)), request(project_id), events.append)
    assert events[-1].error_code == JobErrorCodeEnum.INTERNAL_ERROR
