from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.errors import SERVICE_ERRORS, http_error
from app.core.config import (
    ERROR_NOT_AUTHENTICATED,
    ERROR_PROJECT_NOT_FOUND,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
    SESSION_COOKIE_SAMESITE,
    get_settings,
)
from app.database.models import AuthSession, Project, User
from app.database.session import get_db
from app.services.auth.auth import renew_if_due, resolve_session
from app.services.projects.projects import ProjectNotFoundError, get_project


@dataclass(frozen=True)
class CurrentSession:
    user: User
    session: AuthSession
    token: str


def get_current_session(request: Request, response: Response, db: Session = Depends(get_db)) -> CurrentSession:
    """The signed-in user of this request, or 401; a session past half its lifetime is renewed here (WCAG 2.2.1)."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    session = resolve_session(db, token)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_NOT_AUTHENTICATED)
    if renew_if_due(db, session):
        set_session_cookie(response, token)
    return CurrentSession(user=session.user, session=session, token=token)


def get_current_user(current: CurrentSession = Depends(get_current_session)) -> User:
    return current.user


def owns(user: User, project: Project) -> bool:
    return project.owner_id == user.id


def require_project_access(
    project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Project:
    """The project, if the signed-in user owns it; someone else's project answers 404, like a missing one (MS3 §1.1.6)."""
    try:
        project = get_project(db, project_id)
    except SERVICE_ERRORS as exc:
        raise http_error(exc) from exc
    if not owns(user, project):
        raise http_error(ProjectNotFoundError(ERROR_PROJECT_NOT_FOUND.format(project_id=project_id)))
    return project


def set_session_cookie(response: Response, token: str) -> None:
    """httpOnly so scripts cannot read it, SameSite so other sites cannot send it, Secure once behind TLS."""
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_ttl_seconds,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
        secure=settings.session_cookie_secure,
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
        secure=settings.session_cookie_secure,
    )
