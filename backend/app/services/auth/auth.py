import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import (
    ERROR_EMAIL_TAKEN,
    ERROR_INVALID_CREDENTIALS,
    ERROR_WRONG_PASSWORD,
    IP_ADDRESS_MAX_LENGTH,
    LOGIN_REASON_ACCOUNT_CONFLICT,
    SESSION_RENEW_FRACTION,
    SESSION_TOKEN_BYTES,
    USER_AGENT_MAX_LENGTH,
    USER_NAME_MAX_LENGTH,
    AgeGroup,
    LoginErrorCode,
    get_settings,
)
from app.database.base import utc_now
from app.database.models import AuthSession, User
from app.services.auth.identity_provider import IdentityClaims, LoginRejectedError

# Argon2id with argon2-cffi's default parameters (RFC 9106); each hash carries its own salt (MS3 §1.1.6).
_hasher = PasswordHasher()
# Checked when the email is unknown or the account is locked, so a sign-in takes the same time in every case.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(SESSION_TOKEN_BYTES))


class EmailTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    """Sign-in refused; the message never says whether the email exists, the account is locked or disabled."""


class WrongPasswordError(Exception):
    """The current password given to confirm an account change is wrong."""


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


def password_matches(password_hash: str, password: str) -> bool:
    if password_hash is None:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _lifetime() -> timedelta:
    return timedelta(seconds=get_settings().session_ttl_seconds)


def _truncate(value: Optional[str], limit: int) -> Optional[str]:
    return value[:limit] if value else None


def create_user(db: Session, email: str, name: str, password: str, age_group: AgeGroup = AgeGroup.ADULT) -> User:
    """Register an account; the email is stored lower-cased and must be unique."""
    user = User(email=normalize_email(email), name=name, password_hash=_hasher.hash(password), age_group=age_group)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise EmailTakenError(ERROR_EMAIL_TAKEN) from error
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """Return the account these credentials sign in to, or raise InvalidCredentialsError.

    A locked account is refused even with the right password; a successful sign-in resets the failure count.
    """
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    now = utc_now()
    if user is None or (user.locked_until is not None and user.locked_until > now):
        password_matches(_DUMMY_HASH, password)
        raise InvalidCredentialsError(ERROR_INVALID_CREDENTIALS)
    if not password_matches(user.password_hash, password):
        _record_failed_login(db, user, now)
        raise InvalidCredentialsError(ERROR_INVALID_CREDENTIALS)
    if not user.is_active:
        raise InvalidCredentialsError(ERROR_INVALID_CREDENTIALS)
    user.failed_login_count = 0
    user.locked_until = None
    # Hashes made with older parameters are upgraded while the plain password is at hand.
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    db.commit()
    return user


def provision_user(db: Session, claims: IdentityClaims) -> User:
    """Keycloak is the source of truth: name, email, age group and the admin role are copied at each sign-in.

    The account is found by its Keycloak subject, so a changed email keeps the same account and projects.
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


def _record_failed_login(db: Session, user: User, now: datetime) -> None:
    """Count a wrong password in one UPDATE, so parallel attempts cannot slip past the limit (MS3 §1.1.6)."""
    settings = get_settings()
    failures = db.execute(
        update(User)
        .where(User.id == user.id)
        .values(failed_login_count=User.failed_login_count + 1)
        .returning(User.failed_login_count)
    ).scalar_one()
    if failures >= settings.login_max_failed_attempts:
        db.execute(
            update(User)
            .where(User.id == user.id)
            .values(failed_login_count=0, locked_until=now + timedelta(seconds=settings.login_lockout_seconds))
        )
    db.commit()


def create_session(
    db: Session,
    user: User,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    idp_session_id: Optional[str] = None,
    authenticated_at: Optional[datetime] = None,
) -> NewSession:
    """idp_session_id and authenticated_at come from the Keycloak sign-in that opened this session."""
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
    """The live session of this token; None when it is missing, unknown, expired or its account is disabled."""
    if not token:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None or session.expires_at <= utc_now() or not session.user.is_active:
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
    if session.authenticated_at is None:
        return False
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


def revoke_user_sessions(db: Session, user_id: uuid.UUID, keep: Optional[uuid.UUID] = None) -> None:
    """End every session of the user, except `keep` (the browser making the request) when given."""
    statement = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep is not None:
        statement = statement.where(AuthSession.id != keep)
    db.execute(statement)
    db.commit()


def change_password(
    db: Session, user: User, current_password: str, new_password: str, keep_session: AuthSession
) -> None:
    """Set a new password and sign out every other session, in one transaction."""
    if not password_matches(user.password_hash, current_password):
        raise WrongPasswordError(ERROR_WRONG_PASSWORD)
    user.password_hash = _hasher.hash(new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.id != keep_session.id))
    db.commit()


def purge_expired_sessions(db: Session) -> int:
    """Delete the sessions that have expired (called by the periodic sweep); returns how many."""
    result = db.execute(delete(AuthSession).where(AuthSession.expires_at <= utc_now()))
    db.commit()
    return result.rowcount
