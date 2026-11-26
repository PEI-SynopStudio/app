from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.config import AgeGroup


class UserResponse(BaseModel):
    """The signed-in account; name, email and password are changed on the Keycloak account page."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    is_admin: bool
    age_group: AgeGroup
    created_at: datetime
