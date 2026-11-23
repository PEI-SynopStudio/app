from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """A supporting document of a project (FR03); its storage key stays on the server."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_name: str
    file_type: str
    content_type: Optional[str]
    size_bytes: int
    created_at: datetime