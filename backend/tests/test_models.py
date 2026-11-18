import uuid
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import (
    AuditAction,
    JobStatusEnum,
    JobTypeEnum,
    LicenseType,
    MediaAssetStatus,
    ProjectStatus,
    SourceType,
)
from app.database.base import utc_now
from app.database.models import (
    AudioTrack,
    AuditLog,
    Job,
    MediaAsset,
    Project,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
    UploadSession,
)


def make_project():
    return Project(
        title="Debate",
        author="University of Aveiro",
        speakers=["Ana", "Rui"],
        recording_date=date(2026, 10, 1),
        license_type=LicenseType.CREATIVE_COMMONS,
        copyright_notice="CC BY 4.0",
        licence_confirmed=True,
        authorship_confirmed=True,
    )


def make_asset(project):
    return MediaAsset(
        project=project, source_type=SourceType.UPLOAD, file_name="debate.mp4", status=MediaAssetStatus.PROCESSING
    )


def make_track(asset):
    return AudioTrack(media_asset=asset, sample_rate=16000, channels=1, format="wav", storage_key="audio/audio.wav")


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_project_keeps_the_fr01_metadata(db):
    project = make_project()
    db.add(project)
    db.commit()
    db.expire_all()

    stored = db.get(Project, project.id)
    assert stored.speakers == ["Ana", "Rui"]
    assert stored.recording_date == date(2026, 10, 1)
    assert stored.status == ProjectStatus.DRAFT
    assert stored.owner_id is None


def test_enums_are_stored_by_value(db):
    db.add(make_project())
    db.commit()

    row = db.execute(text("SELECT status, license_type FROM projects")).one()
    assert tuple(row) == ("draft", "creative_commons")


def test_timestamps_are_timezone_aware(db):
    project = make_project()
    db.add(project)
    db.commit()
    db.expire_all()

    assert db.get(Project, project.id).created_at.tzinfo is not None


def test_a_media_asset_has_only_one_audio_track(db):
    asset = make_asset(make_project())
    db.add(make_track(asset))
    db.commit()

    db.add(AudioTrack(media_asset_id=asset.id, sample_rate=16000, channels=1, format="wav", storage_key="other.wav"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_a_project_removes_its_media(db):
    project = make_project()
    db.add(make_track(make_asset(project)))
    db.commit()
    db.expire_all()

    db.delete(project)
    db.commit()

    assert (count(db, Project), count(db, MediaAsset), count(db, AudioTrack)) == (0, 0, 0)


def saved_project(db):
    project = make_project()
    db.add(project)
    db.commit()
    return project


def saved_asset(db, project):
    asset = make_asset(project)
    db.add(asset)
    db.commit()
    return asset


def make_job(project, **kwargs):
    kwargs.setdefault("job_type", JobTypeEnum.INGESTION)
    return Job(project_id=project.id, parameters={}, **kwargs)


def make_upload(project, asset):
    return UploadSession(
        project_id=project.id,
        media_asset_id=asset.id,
        file_name="debate.mp4",
        size_bytes=10,
        chunk_size=4,
        total_chunks=3,
        staged_file="session.mp4",
        storage_upload_id="storage-upload",
        expires_at=utc_now(),
    )


def make_audit_entry(project):
    return AuditLog(project_id=project.id, action=AuditAction.PROJECT_CREATED)


def test_a_project_has_only_one_active_ingestion(db):
    project = saved_project(db)
    db.add(make_job(project))
    db.commit()

    db.add(make_job(project, status=JobStatusEnum.QUEUED))
    with pytest.raises(IntegrityError):
        db.commit()


def test_a_finished_ingestion_allows_a_new_one(db):
    project = saved_project(db)
    db.add(make_job(project, status=JobStatusEnum.FAILED))
    db.commit()

    db.add(make_job(project))
    db.commit()

    assert count(db, Job) == 2


def test_ingestion_and_transcription_limits_are_separate(db):
    project = saved_project(db)
    db.add_all([make_job(project), make_job(project, job_type=JobTypeEnum.TRANSCRIPTION)])
    db.commit()

    assert count(db, Job) == 2


def test_a_project_has_only_one_active_transcription(db):
    project = saved_project(db)
    db.add(make_job(project, job_type=JobTypeEnum.TRANSCRIPTION))
    db.commit()

    db.add(make_job(project, job_type=JobTypeEnum.TRANSCRIPTION, status=JobStatusEnum.QUEUED))
    with pytest.raises(IntegrityError):
        db.commit()


def test_job_exposes_the_id_expected_by_the_api(db):
    job = make_job(saved_project(db))
    db.add(job)
    db.commit()

    assert job.job_id == job.id


def test_deleting_a_media_asset_keeps_the_job_history(db):
    project = saved_project(db)
    asset = saved_asset(db, project)
    job = make_job(project, media_asset_id=asset.id, status=JobStatusEnum.COMPLETED)
    db.add(job)
    db.commit()
    db.expire_all()

    db.delete(db.get(MediaAsset, asset.id))
    db.commit()
    db.expire_all()

    assert db.get(Job, job.id).media_asset_id is None


def test_deleting_a_project_keeps_only_the_audit_log(db):
    project = saved_project(db)
    asset = saved_asset(db, project)
    db.add_all([make_job(project), make_upload(project, asset), make_audit_entry(project)])
    db.commit()
    db.expire_all()

    db.delete(project)
    db.commit()

    assert (count(db, Job), count(db, UploadSession), count(db, AuditLog)) == (0, 0, 1)


def test_audit_entries_cannot_be_changed(db):
    entry = make_audit_entry(saved_project(db))
    db.add(entry)
    db.commit()

    entry.details = {"changed": True}
    with pytest.raises(RuntimeError, match="cannot be changed"):
        db.commit()


def test_audit_entries_cannot_be_deleted(db):
    entry = make_audit_entry(saved_project(db))
    db.add(entry)
    db.commit()

    db.delete(entry)
    with pytest.raises(RuntimeError, match="cannot be changed"):
        db.commit()


def make_transcript(project, asset, words=("Bom", "dia")):
    transcript = Transcript(
        id=uuid.uuid4(),
        project_id=project.id,
        media_asset_id=asset.id,
        language="pt",
        model_name="large-v3-turbo",
        model_revision="a" * 40,
        alignment_model_name="wav2vec2",
        alignment_model_revision="b" * 40,
        parameters={"beam_size": 5},
        time_offset_seconds=0.0,
        storage_key="transcript/transcript.json",
        segment_count=1,
        word_count=len(words),
        aligned_word_count=len(words),
    )
    segment = TranscriptSegment(
        position=0, text=" ".join(words), start_seconds=0.0, end_seconds=1.0, confidence=0.9,
        avg_logprob=-0.2, no_speech_prob=0.01, compression_ratio=1.1, temperature=0.0,
    )
    segment.words = [
        TranscriptWord(
            transcript_id=transcript.id, position=index, text=text, start_seconds=index * 0.5,
            end_seconds=index * 0.5 + 0.4, confidence=0.9, aligned=True,
        )
        for index, text in enumerate(words)
    ]
    transcript.segments = [segment]
    return transcript


def test_transcript_keeps_its_segments_and_words_in_order(db):
    project = saved_project(db)
    transcript = make_transcript(project, saved_asset(db, project), words=("Bom", "dia", "a", "todos"))
    db.add(transcript)
    db.commit()
    db.expire_all()

    stored = db.get(Transcript, transcript.id)
    assert stored.ai_generated is True
    assert [word.text for word in stored.segments[0].words] == ["Bom", "dia", "a", "todos"]


def test_a_media_asset_has_only_one_transcript(db):
    project = saved_project(db)
    asset = saved_asset(db, project)
    db.add(make_transcript(project, asset))
    db.commit()

    db.add(make_transcript(project, asset))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_a_media_asset_removes_its_transcript(db):
    project = saved_project(db)
    asset = saved_asset(db, project)
    db.add(make_transcript(project, asset))
    db.commit()

    db.delete(asset)
    db.commit()

    assert (count(db, Transcript), count(db, TranscriptSegment), count(db, TranscriptWord)) == (0, 0, 0)


def test_two_words_of_a_transcript_cannot_share_a_position(db):
    project = saved_project(db)
    transcript = make_transcript(project, saved_asset(db, project))
    transcript.segments[0].words[1].position = 0
    db.add(transcript)

    with pytest.raises(IntegrityError):
        db.commit()
