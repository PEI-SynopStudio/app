from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_project_access
from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import CLIP_ROUTE, CLIPS_ROUTE, CLIPS_ROUTE_TAG, PROJECTS_ROUTE_PREFIX
from app.database.models import User
from app.database.session import get_db
from app.schemas.clip import ClipCreate, ClipResponse, ClipUpdate
from app.services.projects.clips import create_clip, delete_clip, get_clip, list_clips, update_clip

# Every route needs a signed-in user who owns the project; another user's project answers 404 (MS3 §1.1.6).
router = APIRouter(
    prefix=PROJECTS_ROUTE_PREFIX, tags=[CLIPS_ROUTE_TAG], dependencies=[Depends(require_project_access)]
)


# Return the clips of a project in their order.
# Source: MS2 FR10 (clip proposals), US18 (the intervals of the original video each clip comes from).
@router.get(CLIPS_ROUTE, response_model=List[ClipResponse])
def read_clips(project_id: str, db: Session = Depends(get_db)):
    try:
        return [ClipResponse.model_validate(clip) for clip in list_clips(db, project_id)]
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Create a clip from parts of the original video.
# Source: MS2 FR10, FR11, FR12; FR18 (audit).
@router.post(CLIPS_ROUTE, status_code=status.HTTP_201_CREATED, response_model=ClipResponse)
def create(
    project_id: str,
    body: ClipCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return ClipResponse.model_validate(create_clip(db, project_id, body, actor=user))
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


@router.get(CLIP_ROUTE, response_model=ClipResponse)
def read(project_id: str, clip_id: str, db: Session = Depends(get_db)):
    try:
        return ClipResponse.model_validate(get_clip(db, project_id, clip_id))
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


# Rename a clip, change its scenes or the language of its subtitles; omitted fields keep their value.
# Source: MS2 FR12, US21; FR18, US30.
@router.patch(CLIP_ROUTE, response_model=ClipResponse)
def update(
    project_id: str,
    clip_id: str,
    body: ClipUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return ClipResponse.model_validate(update_clip(db, project_id, clip_id, body, actor=user))
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc


@router.delete(CLIP_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def delete(
    project_id: str,
    clip_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        delete_clip(db, project_id, clip_id, actor=user)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc