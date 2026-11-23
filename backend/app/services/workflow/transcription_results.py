import tempfile
import uuid
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.config import (
    AUDIT_DETAIL_ERROR_CODE,
    AUDIT_DETAIL_JOB_ID,
    AUDIT_TRANSCRIPTION_FIELDS,
    ERROR_TRANSCRIPT_COUNT_MISMATCH,
    JSON_DUMP_MODE,
    TRANSCRIPT_FILE,
    AuditAction,
    JobStatusEnum,
    JobTypeEnum,
    ProjectStatus,
)
from app.database.models import Job, Project, Transcript, TranscriptSegment, TranscriptWord
from app.schemas.transcript import TranscriptDocument, TranscriptionOutput
from app.services.audit.audit import record_audit
from app.services.storage.object_storage import ObjectStorage


def record_transcription_outcome(
    db: Session, job: Job, open_object_storage: Optional[Callable[[], ObjectStorage]] = None
) -> None:
    if job.job_type != JobTypeEnum.TRANSCRIPTION:
        return
    project = db.get(Project, job.project_id)

    if job.status == JobStatusEnum.PROCESSING:
        project.status = ProjectStatus.TRANSCRIBING
    elif job.status == JobStatusEnum.COMPLETED:
        _record_success(db, job, project, open_object_storage)
    elif job.status == JobStatusEnum.FAILED:
        project.status = ProjectStatus.TRANSCRIPTION_FAILED
        record_audit(
            db,
            project.id,
            AuditAction.TRANSCRIPTION_FAILED,
            {AUDIT_DETAIL_JOB_ID: str(job.id), AUDIT_DETAIL_ERROR_CODE: job.error_code.value},
        )


def _record_success(
    db: Session, job: Job, project: Project, open_object_storage: Callable[[], ObjectStorage]
) -> None:
    output = TranscriptionOutput.model_validate(job.output)
    if job.media_asset_id is not None:
        document = _load_document(open_object_storage(), str(job.project_id), output.transcript_key)
        db.add(_build_transcript(job, output, document))
    project.status = ProjectStatus.TRANSCRIBED
    record_audit(
        db,
        project.id,
        AuditAction.TRANSCRIPTION_COMPLETED,
        {AUDIT_DETAIL_JOB_ID: str(job.id), **output.model_dump(mode=JSON_DUMP_MODE, include=AUDIT_TRANSCRIPTION_FIELDS)},
    )


def _load_document(object_storage: ObjectStorage, project_id: str, key: str) -> TranscriptDocument:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / TRANSCRIPT_FILE
        object_storage.get_file(project_id, key, path)
        return TranscriptDocument.model_validate_json(path.read_bytes())


def _build_transcript(job: Job, output: TranscriptionOutput, document: TranscriptDocument) -> Transcript:
    """Raises ValueError when the stored document does not hold the words the worker reported."""
    transcript = Transcript(
        id=uuid.uuid4(),
        project_id=job.project_id,
        media_asset_id=job.media_asset_id,
        job_id=job.id,
        language=output.language,
        model_name=output.model_name,
        model_revision=output.model_revision,
        alignment_model_name=output.alignment_model_name,
        alignment_model_revision=output.alignment_model_revision,
        parameters=output.parameters,
        time_offset_seconds=output.time_offset_seconds,
        storage_key=output.transcript_key,
        ai_generated=document.ai_generated,
        segment_count=output.segment_count,
        word_count=output.word_count,
        aligned_word_count=output.aligned_word_count,
    )
    position = 0
    for index, segment in enumerate(document.segments):
        stored = TranscriptSegment(
            position=index,
            text=segment.text,
            start_seconds=segment.start,
            end_seconds=segment.end,
            confidence=segment.confidence,
            avg_logprob=segment.avg_logprob,
            no_speech_prob=segment.no_speech_prob,
            compression_ratio=segment.compression_ratio,
            temperature=segment.temperature,
        )
        for word in segment.words:
            stored.words.append(TranscriptWord(
                transcript_id=transcript.id,
                position=position,
                text=word.text,
                start_seconds=word.start,
                end_seconds=word.end,
                confidence=word.confidence,
                aligned=word.aligned,
            ))
            position += 1
        transcript.segments.append(stored)
    if (len(document.segments), position) != (output.segment_count, output.word_count):
        raise ValueError(
            ERROR_TRANSCRIPT_COUNT_MISMATCH.format(
                segments=len(document.segments), words=position, expected_segments=output.segment_count, expected_words=output.word_count
            )
        )
    return transcript
