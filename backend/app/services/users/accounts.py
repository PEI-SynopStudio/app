from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ERROR_ACCOUNT_BUSY, JOB_ACTIVE_STATUSES
from app.database.models import Job, User
from app.services.auth.identity_provider import IdentityProvider
from app.services.projects.projects import delete_project, list_projects
from app.services.storage.local import LocalStorage
from app.services.storage.object_storage import ObjectStorage


class AccountBusyError(Exception):
    pass


# Delete the account with all its projects and their data, here and at Keycloak; only the audit records remain.
# Source: MS3 §1.1.2, §1.4.3 (account deletion, audit records kept for 12 months); GDPR Art. 17.
def delete_account(
    db: Session,
    storage: LocalStorage,
    object_storage: ObjectStorage,
    identity_provider: IdentityProvider,
    user: User,
) -> None:
    """Refused while a project has an active ingestion, because its worker would keep writing files for it.

    Order: projects (objects first, see delete_project), then the Keycloak account, then the local one.
    If storage or Keycloak fails part way, the local account stays, so the user can still sign in and
    repeat the deletion; Keycloak counts an account it no longer has as deleted.
    """
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
    if user.subject is not None:
        identity_provider.delete_user(user.subject)
    db.delete(user)  # its sessions go with it (ON DELETE CASCADE)
    db.commit()
