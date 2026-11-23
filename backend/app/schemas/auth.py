from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.core.config import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    USER_NAME_MAX_LENGTH,
    USER_NAME_MIN_LENGTH,
    AgeGroup,
)

UserName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=USER_NAME_MIN_LENGTH, max_length=USER_NAME_MAX_LENGTH)
]
NewPassword = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]
# No minimum when signing in: a policy change must not lock out accounts with older, shorter passwords.
AnyPassword = Annotated[str, Field(max_length=PASSWORD_MAX_LENGTH)]


class RegisterRequest(BaseModel):
    email: EmailStr
    name: UserName
    password: NewPassword
    # Required: users under 13 have no value to choose; 13–17 need a guardian's consent (MS3 §1.4.1).
    age_group: AgeGroup


class LoginRequest(BaseModel):
    email: EmailStr
    password: AnyPassword


class PasswordChangeRequest(BaseModel):
    current_password: AnyPassword
    new_password: NewPassword


class ProfileUpdateRequest(BaseModel):
    """Only the fields sent are changed (GDPR Art. 16, rectification)."""

    name: Optional[UserName] = None
    email: Optional[EmailStr] = None
    # Required to change the email, which is what the account signs in with.
    current_password: Optional[AnyPassword] = None


class AccountDeleteRequest(BaseModel):
    password: AnyPassword


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    is_admin: bool
    age_group: AgeGroup
    created_at: datetime
