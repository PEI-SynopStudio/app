from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import PROJECTS_ROUTE_PREFIX, TRANSCRIPT_ROUTE, TRANSCRIPTS_ROUTE_TAG, VIDEO_START_SECONDS
from app.database.session import get_db
from app.schemas.transcript import TranscriptResponse
from app.services.transcripts.transcripts import read_transcript

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
