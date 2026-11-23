import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import AuditAction, JobErrorCodeEnum, JobStatusEnum, JobStepProcessingEnum, ProjectStatus
from app.database.models import AuditLog, Project, Transcript, TranscriptSegment, TranscriptWord
from app.schemas import transcript as schema
from app.schemas.job import JobUpdateEventSchema, TranscriptionParams
from app.services.workflow.jobs import apply_job_event, create_transcription_job, fail_job, queue_job
from in_memory_object_storage import InMemoryObjectStorage
from test_submission import finished_asset, make_project, storage  # noqa: F401

TRANSCRIPT_KEY = "transcript/transcript.json"


def word(text, start, aligned=True):
    return schema.TranscriptWord(text=text, start=start, end=start + 0.3, confidence=0.9, aligned=aligned)


def document():
    segments = [
        schema.TranscriptSegment(
            text="Bom dia.", start=1.0, end=1.65, confidence=0.9, avg_logprob=-0.2, no_speech_prob=0.01,
            compression_ratio=1.1, temperature=0.0, words=[word("Bom", 1.0), word("dia.", 1.35)],
        ),
        schema.TranscriptSegment(
            text="Em 2024.", start=2.0, end=2.65, confidence=0.8, avg_logprob=-0.4, no_speech_prob=0.02,
            compression_ratio=1.2, temperature=0.2, words=[word("Em", 2.0), word("2024.", 2.35, aligned=False)],
        ),
    ]
    return schema.TranscriptDocument(language="pt", segments=segments)


def output(**changes):
    values = dict(
        transcript_key=TRANSCRIPT_KEY,
        language="pt",
        model_name="large-v3-turbo",
        model_revision="a" * 40,
        alignment_model_name="wav2vec2-pt",
        alignment_model_revision="b" * 40,
        parameters={"beam_size": 5},
        time_offset_seconds=0.0,
        segment_count=2,
        word_count=4,
        aligned_word_count=3,
    )
    return schema.TranscriptionOutput(**{**values, **changes}).model_dump(mode="json")


@pytest.fixture
def transcription(db, storage):
    """A running transcription job of an ingested video, and the storage holding what its worker wrote."""
    project_id = make_project(db)
    asset, _ = finished_asset(db, storage, project_id)
    job = queue_job(db, create_transcription_job(db, project_id, TranscriptionParams(media_id=asset.id), asset.id))
    object_storage = InMemoryObjectStorage()
    object_storage.objects[(project_id, TRANSCRIPT_KEY)] = document().model_dump_json().encode()
    apply_job_event(db, event(job, step=JobStepProcessingEnum.INITIALIZING, step_progress=0), lambda: object_storage)
    return job, object_storage


def event(job, **kwargs):
    kwargs.setdefault("status", JobStatusEnum.PROCESSING)
    kwargs.setdefault("step", JobStepProcessingEnum.TRANSCRIBING)
    kwargs.setdefault("step_progress", 10)
    return JobUpdateEventSchema(job_id=job.id, **kwargs)


def completed(job, **changes):
    return event(job, status=JobStatusEnum.COMPLETED, step=None, step_progress=100, output=output(**changes))


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_a_running_transcription_marks_the_project(db, transcription):
    job, object_storage = transcription

    apply_job_event(db, event(job), lambda: object_storage)

    assert db.get(Project, job.project_id).status == ProjectStatus.TRANSCRIBING


def test_a_completed_transcription_is_stored_word_by_word(db, transcription):
    job, object_storage = transcription

    apply_job_event(db, completed(job), lambda: object_storage)

    db.expire_all()
    stored = db.scalar(select(Transcript))
    assert (stored.media_asset_id, stored.job_id, stored.ai_generated) == (job.media_asset_id, job.id, True)
    assert (stored.model_revision, stored.alignment_model_name, stored.word_count) == ("a" * 40, "wav2vec2-pt", 4)
    assert [segment.text for segment in stored.segments] == ["Bom dia.", "Em 2024."]
    assert [(w.position, w.text, w.aligned) for s in stored.segments for w in s.words] == [
        (0, "Bom", True), (1, "dia.", True), (2, "Em", True), (3, "2024.", False)
    ]
    assert stored.segments[1].temperature == 0.2
    assert db.get(Project, job.project_id).status == ProjectStatus.TRANSCRIBED


def test_a_completed_transcription_is_audited_with_its_models(db, transcription):
    job, object_storage = transcription

    apply_job_event(db, completed(job), lambda: object_storage)

    entry = db.scalar(select(AuditLog).where(AuditLog.action == AuditAction.TRANSCRIPTION_COMPLETED))
    assert entry.details == {
        "job_id": str(job.id),
        "language": "pt",
        "model_name": "large-v3-turbo",
        "model_revision": "a" * 40,
        "alignment_model_name": "wav2vec2-pt",
        "alignment_model_revision": "b" * 40,
        "word_count": 4,
    }


def test_a_repeated_completion_stores_the_transcript_once(db, transcription):
    job, object_storage = transcription
    final = completed(job)

    apply_job_event(db, final, lambda: object_storage)
    apply_job_event(db, final, lambda: object_storage)

    assert (count(db, Transcript), count(db, TranscriptWord)) == (1, 4)


def test_a_transcript_that_does_not_match_the_report_is_refused(db, transcription):
    job, object_storage = transcription

    with pytest.raises(ValueError, match="worker reported"):
        apply_job_event(db, completed(job, word_count=5), lambda: object_storage)

    db.rollback()
    assert (count(db, Transcript), count(db, TranscriptSegment)) == (0, 0)
    assert db.get(Project, job.project_id).status != ProjectStatus.TRANSCRIBED


def test_a_failed_transcription_marks_the_project_and_is_audited(db, transcription):
    job, object_storage = transcription
    failed = event(job, status=JobStatusEnum.FAILED, step_progress=0, error_code=JobErrorCodeEnum.NO_SPEECH_DETECTED, error_message="none")

    apply_job_event(db, failed, lambda: object_storage)

    assert db.get(Project, job.project_id).status == ProjectStatus.TRANSCRIPTION_FAILED
    entry = db.scalar(select(AuditLog).where(AuditLog.action == AuditAction.TRANSCRIPTION_FAILED))
    assert entry.details == {"job_id": str(job.id), "error_code": "no_speech_detected"}
    assert count(db, Transcript) == 0


def test_a_transcription_failed_by_the_backend_also_marks_the_project(db, transcription):
    job, _ = transcription

    fail_job(db, job, JobErrorCodeEnum.TIMEOUT, "silent worker")

    assert db.get(Project, job.project_id).status == ProjectStatus.TRANSCRIPTION_FAILED
