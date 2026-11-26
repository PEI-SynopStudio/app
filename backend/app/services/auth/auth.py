import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import (
    IP_ADDRESS_MAX_LENGTH,
    LOGIN_REASON_ACCOUNT_CONFLICT,
    SESSION_RENEW_FRACTION,
    SESSION_TOKEN_BYTES,
    USER_AGENT_MAX_LENGTH,
    USER_NAME_MAX_LENGTH,
    LoginErrorCode,
    get_settings,
)
from app.database.base import utc_now
from app.database.models import AuthSession, User
from app.services.auth.identity_provider import IdentityClaims, LoginRejectedError


@dataclass(frozen=True)
class NewSession:
    """The raw token goes into the cookie once; only its hash is kept."""

    token: str
    session: AuthSession


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def actor_hash(user_id: uuid.UUID) -> str:
    """What logs and the audit log store instead of the user's email (MS3 §1.1.3)."""
    return hashlib.sha256(str(user_id).encode()).hexdigest()


def _lifetime() -> timedelta:
    return timedelta(seconds=get_settings().session_ttl_seconds)


def _truncate(value: Optional[str], limit: int) -> Optional[str]:
    return value[:limit] if value else None


# Create the account on its first sign-in through Keycloak, and refresh it on every later one.
# Source: architecture §2 (Keycloak owns the accounts); MS3 §1.1.2 (name, email and age group only).
def provision_user(db: Session, claims: IdentityClaims) -> User:
    """Keycloak is the source of truth: name, email, age group and the admin role are copied at each sign-in.

    The account is found by its Keycloak subject, so a changed email keeps the same account and projects.
    Two first sign-ins of the same account at once can both try to create it; the second is refused.
    """
    user = db.scalar(select(User).where(User.subject == claims.subject))
    if user is None:
        user = User(subject=claims.subject)
        db.add(user)
    user.email = normalize_email(claims.email)
    # Keycloak allows a first and a last name of 60 characters each, one more than the column holds.
    user.name = claims.name[:USER_NAME_MAX_LENGTH]
    user.age_group = claims.age_group
    user.is_admin = claims.is_admin
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise LoginRejectedError(LoginErrorCode.LOGIN_FAILED, LOGIN_REASON_ACCOUNT_CONFLICT) from exc
    db.refresh(user)
    return user


def create_session(
    db: Session,
    user: User,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    *,
    authenticated_at: datetime,
    idp_session_id: Optional[str] = None,
) -> NewSession:
    """authenticated_at and idp_session_id come from the Keycloak sign-in that opened this session."""
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        ip_address=_truncate(ip_address, IP_ADDRESS_MAX_LENGTH),
        user_agent=_truncate(user_agent, USER_AGENT_MAX_LENGTH),
        expires_at=utc_now() + _lifetime(),
        idp_session_id=idp_session_id,
        authenticated_at=authenticated_at,
    )
    db.add(session)
    db.commit()
    return NewSession(token=token, session=session)


def resolve_session(db: Session, token: Optional[str]) -> Optional[AuthSession]:
    """The live session of this token; None when it is missing, unknown or expired."""
    if not token:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None or session.expires_at <= utc_now():
        return None
    return session


def renew_if_due(db: Session, session: AuthSession) -> bool:
    """Give a session in use a new full lifetime once part of it has passed, so it never runs out mid-task (WCAG 2.2.1).

    Returns whether it was renewed, so the caller can send the cookie again with the new expiry.
    """
    lifetime = _lifetime()
    now = utc_now()
    if session.expires_at - now > lifetime * (1 - SESSION_RENEW_FRACTION):
        return False
    session.expires_at = now + lifetime
    db.commit()
    return True


def is_recently_authenticated(session: AuthSession) -> bool:
    """Whether the password was entered at Keycloak recently enough to delete the account (T4.25)."""
    return utc_now() - session.authenticated_at <= timedelta(seconds=get_settings().reauth_max_age_seconds)


def revoke_session(db: Session, token: Optional[str]) -> Optional[str]:
    """End the session of this token; returns its Keycloak session, so the caller can end that one too."""
    if not token:
        return None
    idp_session_id = db.scalar(
        delete(AuthSession).where(AuthSession.token_hash == hash_token(token)).returning(AuthSession.idp_session_id)
    )
    db.commit()
    return idp_session_id


def revoke_user_sessions(db: Session, user_id: uuid.UUID) -> None:
    """End every session of the user (signing out everywhere)."""
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    db.commit()


def purge_expired_sessions(db: Session) -> int:
    """Delete the sessions that have expired (called by the periodic sweep); returns how many."""
    result = db.execute(delete(AuthSession).where(AuthSession.expires_at <= utc_now()))
    db.commit()
    return result.rowcount
