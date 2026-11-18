from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import (
    ERROR_MEDIA_NOT_READY,
    PROXY_CONTENT_TYPE,
    WAVEFORM_CONTENT_TYPE,
    MediaAssetStatus,
    get_settings,
)
from app.database.models import MediaAsset
from app.services.projects.projects import get_project
from app.services.storage.object_storage import ObjectStorage


class MediaNotReadyError(LookupError):
    pass


class MediaLinks(BaseModel):
    proxy_url: str
    waveform_url: str
    # Lets the client ask for new links before these stop working.
    expires_in_seconds: int


# Build the temporary links a browser uses to play a finished video and draw its waveform.
# Source: MS3 §1.1.6 (media files served through signed, time-limited URLs); MS2 FR02 – Outputs.
def media_links(db: Session, object_storage: ObjectStorage, project_id: str) -> MediaLinks:
    """Raises MediaNotReadyError while the project has no finished video."""
    project = get_project(db, project_id)
    query = select(MediaAsset).where(MediaAsset.project_id == project.id, MediaAsset.status == MediaAssetStatus.READY)
    asset = db.scalars(query.order_by(MediaAsset.created_at.desc())).first()
    if asset is None:
        raise MediaNotReadyError(ERROR_MEDIA_NOT_READY.format(project_id=project_id))

    expires = get_settings().s3_signed_url_ttl_seconds
    owner = str(project.id)
    return MediaLinks(
        proxy_url=object_storage.signed_url(owner, asset.proxy_key, PROXY_CONTENT_TYPE, expires),
        waveform_url=object_storage.signed_url(owner, asset.audio_track.waveform_key, WAVEFORM_CONTENT_TYPE, expires),
        expires_in_seconds=expires,
    )
