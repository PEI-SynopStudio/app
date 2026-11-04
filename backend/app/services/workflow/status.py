from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from app.core.config import INGESTION_STATUS_FILE, JSON_DUMP_MODE, IngestionStage
from app.services.storage.local import LocalStorage


class IngestionError(BaseModel):
    code: str
    message: str


class IngestionStatus(BaseModel):
    project_id: str
    stage: IngestionStage
    message: Optional[str] = None
    error: Optional[IngestionError] = None
    updated_at: datetime


def _save(storage: LocalStorage, status: IngestionStatus) -> IngestionStatus:
    storage.write_json(status.project_id, INGESTION_STATUS_FILE, status.model_dump(mode=JSON_DUMP_MODE))
    return status


def set_stage(
    storage: LocalStorage,
    project_id: str,
    stage: IngestionStage,
    message: Optional[str] = None,
) -> IngestionStatus:
    """Record the current ingestion stage, clearing any previous error."""
    return _save(storage, IngestionStatus(
        project_id=project_id,
        stage=stage,
        message=message,
        updated_at=datetime.now(timezone.utc),
    ))


def mark_failed(storage: LocalStorage, project_id: str, error_code: str, message: str) -> IngestionStatus:
    """Set the project to 'Ingestion Failed' with explicit error details (FR02 step 3)."""
    return _save(storage, IngestionStatus(
        project_id=project_id,
        stage=IngestionStage.FAILED,
        message=message,
        error=IngestionError(code=error_code, message=message),
        updated_at=datetime.now(timezone.utc),
    ))


def get_status(storage: LocalStorage, project_id: str) -> Optional[IngestionStatus]:
    data = storage.read_json(project_id, INGESTION_STATUS_FILE)
    return IngestionStatus.model_validate(data) if data is not None else None
