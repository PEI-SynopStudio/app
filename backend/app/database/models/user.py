import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import (
    DB_DELETE_ORPHAN_CASCADE,
    DB_ON_DELETE_CASCADE,
    EMAIL_MAX_LENGTH,
    FK_USER_ID,
    IDP_SESSION_ID_MAX_LENGTH,
    IP_ADDRESS_MAX_LENGTH,
    SUBJECT_MAX_LENGTH,
    TABLE_AUTH_SESSIONS,
    TABLE_USERS,
    TOKEN_HASH_LENGTH,
    USER_AGENT_MAX_LENGTH,
    USER_NAME_MAX_LENGTH,
    AgeGroup,
)
from app.database.base import Base, enum_type, utc_now


class User(Base):
    """An account of the app, linked to its Keycloak account; it holds only the data MS3 §1.1.2 lists.

    Keycloak owns the password, the lockout and the account status; this row is refreshed at each sign-in.
    """

    __tablename__ = TABLE_USERS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The Keycloak "sub" claim: the stable link to the identity provider account (architecture §2).
    subject: Mapped[str] = mapped_column(String(SUBJECT_MAX_LENGTH), unique=True, index=True)
    # A copy of the Keycloak email, stored lower-cased; Keycloak keeps it unique, so this column does not.
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    name: Mapped[str] = mapped_column(String(USER_NAME_MAX_LENGTH))
    age_group: Mapped[AgeGroup] = mapped_column(enum_type(AgeGroup))
    # Copied from the Keycloak realm role "admin" at each sign-in.
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)

    sessions: Mapped[List["AuthSession"]] = relationship(
        back_populates="user", cascade=DB_DELETE_ORPHAN_CASCADE, passive_deletes=True
    )


class AuthSession(Base):
    """A signed-in browser. Only the SHA-256 of the token is stored, so a database leak gives no usable session."""

    __tablename__ = TABLE_AUTH_SESSIONS

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(FK_USER_ID, ondelete=DB_ON_DELETE_CASCADE), index=True)
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    # Kept for security and abuse handling (MS3 §1.1.2, implicit data).
    ip_address: Mapped[Optional[str]] = mapped_column(String(IP_ADDRESS_MAX_LENGTH))
    user_agent: Mapped[Optional[str]] = mapped_column(String(USER_AGENT_MAX_LENGTH))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    # Moved forward when a session in use renews; indexed for the sweep that deletes expired sessions.
    expires_at: Mapped[datetime] = mapped_column(index=True)
    # The Keycloak session ("sid" claim), ended at Keycloak when this session signs out.
    idp_session_id: Mapped[Optional[str]] = mapped_column(String(IDP_SESSION_ID_MAX_LENGTH))
    # When the user last entered a password at Keycloak ("auth_time"); deleting the account needs a recent one (T4.25).
    authenticated_at: Mapped[datetime]

    user: Mapped[User] = relationship(back_populates="sessions")
