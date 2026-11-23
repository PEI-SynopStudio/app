from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import (
    PROJECTS_ROUTE_PREFIX,
    TRANSCRIPT_ROUTE,
    TRANSCRIPTION_ROUTE,
    TRANSCRIPTS_ROUTE_TAG,
    VIDEO_START_SECONDS,
)
from app.database.session import get_db
from app.schemas.job import JobStatusResponseSchema
from app.schemas.transcript import TranscriptResponse
from app.services.transcripts.transcripts import read_transcript, request_transcription
from app.services.workflow.dispatcher import JobDispatcher
from app.services.workflow.rabbitmq import get_dispatcher

router = APIRouter(prefix=PROJECTS_ROUTE_PREFIX, tags=[TRANSCRIPTS_ROUTE_TAG])

@router.get(TRANSCRIPT_ROUTE, response_model=TranscriptResponse)
def get_transcript(
    project_id: str,
    start: Optional[float] = Query(default=None, ge=VIDEO_START_SECONDS),
    end: Optional[float] = Query(default=None, ge=VIDEO_START_SECONDS),
    db: Session = Depends(get_db),
):
    try:
        return read_transcript(db, project_id, start, end)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


@router.post(TRANSCRIPTION_ROUTE, status_code=status.HTTP_202_ACCEPTED, response_model=JobStatusResponseSchema)
def start_transcription(
    project_id: str,
    db: Session = Depends(get_db),
    dispatcher: JobDispatcher = Depends(get_dispatcher),
):
    try:
        return request_transcription(db, dispatcher, project_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
