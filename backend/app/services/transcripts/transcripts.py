from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import ERROR_TRANSCRIPT_NOT_FOUND, ERROR_TRANSCRIPT_RANGE
from app.database.models import Transcript, TranscriptSegment
from app.schemas import transcript as schema
from app.services.projects.projects import get_project


class TranscriptNotFoundError(LookupError):
    pass



def read_transcript(
    db: Session, project_id: str, start: Optional[float] = None, end: Optional[float] = None
) -> schema.TranscriptResponse:
    if start is not None and end is not None and end <= start:
        raise ValueError(ERROR_TRANSCRIPT_RANGE)
    project = get_project(db, project_id)
    latest = select(Transcript).where(Transcript.project_id == project.id).order_by(Transcript.created_at.desc())
    transcript = db.scalars(latest).first()
    if transcript is None:
        raise TranscriptNotFoundError(ERROR_TRANSCRIPT_NOT_FOUND.format(project_id=project_id))

    query = (
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == transcript.id)
        .options(selectinload(TranscriptSegment.words))
        .order_by(TranscriptSegment.position)
    )
    if start is not None:
        query = query.where(TranscriptSegment.end_seconds > start)
    if end is not None:
        query = query.where(TranscriptSegment.start_seconds < end)
    return schema.TranscriptResponse(
        **schema.TranscriptMetadata.model_validate(transcript).model_dump(),
        segments=[_segment(segment) for segment in db.scalars(query)],
    )


def _segment(segment: TranscriptSegment) -> schema.TranscriptSegment:
    return schema.TranscriptSegment(
        text=segment.text,
        start=segment.start_seconds,
        end=segment.end_seconds,
        confidence=segment.confidence,
        avg_logprob=segment.avg_logprob,
        no_speech_prob=segment.no_speech_prob,
        compression_ratio=segment.compression_ratio,
        temperature=segment.temperature,
        words=[
            schema.TranscriptWord(
                text=word.text, start=word.start_seconds, end=word.end_seconds, confidence=word.confidence, aligned=word.aligned
            )
            for word in segment.words
        ],
    )
