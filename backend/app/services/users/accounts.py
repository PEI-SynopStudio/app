from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import ERROR_ACCOUNT_BUSY, ERROR_EMAIL_TAKEN, ERROR_WRONG_PASSWORD, JOB_ACTIVE_STATUSES
from app.database.models import Job, User
from app.services.auth.auth import EmailTakenError, WrongPasswordError, normalize_email, password_matches
from app.services.projects.projects import delete_project, list_projects
from app.services.storage.local import LocalStorage
from app.services.storage.object_storage import ObjectStorage


class AccountBusyError(Exception):
    pass


# Correct the user's own account data; a new email needs the current password.
# Source: GDPR Art. 16 (rectification); MS3 §1.1.2 (account data).
def update_profile(
    db: Session,
    user: User,
    name: Optional[str] = None,
    email: Optional[str] = None,
    current_password: Optional[str] = None,
) -> User:
    """Raises WrongPasswordError for a new email without the right password, EmailTakenError if it is in use."""
    if email is not None and normalize_email(email) != user.email:
        if current_password is None or not password_matches(user.password_hash, current_password):
            raise WrongPasswordError(ERROR_WRONG_PASSWORD)
        user.email = normalize_email(email)
    if name is not None:
        user.name = name
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise EmailTakenError(ERROR_EMAIL_TAKEN) from exc
    return user


# Delete the account with all its projects and their data; only the licence and editorial audit records remain.
# Source: MS3 §1.1.2, §1.4.3 (account deletion, audit records kept for 12 months); GDPR Art. 17.
def delete_account(
    db: Session, storage: LocalStorage, object_storage: ObjectStorage, user: User, password: str
) -> None:
    """Refused while a project has an active ingestion, because its worker would keep writing files for it.

    Projects are deleted one by one, objects first (see delete_project): if the storage fails part way,
    the account and the projects not reached yet stay, and the deletion can be repeated.
    """
    if not password_matches(user.password_hash, password):
        raise WrongPasswordError(ERROR_WRONG_PASSWORD)
    projects = list_projects(db, user)
    if projects:
        active = (
            select(Job.id)
            .where(Job.project_id.in_([project.id for project in projects]), Job.status.in_(JOB_ACTIVE_STATUSES))
            .limit(1)
        )
        if db.scalar(active) is not None:
            raise AccountBusyError(ERROR_ACCOUNT_BUSY)
    for project in projects:
        delete_project(db, storage, object_storage, str(project.id), actor=user)
    db.delete(user)  # its sessions go with it (ON DELETE CASCADE)
    db.commit()
