from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CurrentSession,
    clear_session_cookie,
    get_current_session,
    get_current_user,
    set_session_cookie,
)
from app.core.config import (
    AUTH_ROUTE_PREFIX,
    AUTH_ROUTE_TAG,
    LOGIN_ROUTE,
    LOGOUT_ALL_ROUTE,
    LOGOUT_ROUTE,
    ME_ROUTE,
    PASSWORD_ROUTE,
    REGISTER_ROUTE,
    SESSION_COOKIE_NAME,
    USER_AGENT_HEADER,
)
from app.database.models import User
from app.database.session import get_db
from app.schemas.auth import (
    AccountDeleteRequest,
    LoginRequest,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    UserResponse,
)
from app.services.auth.auth import (
    EmailTakenError,
    InvalidCredentialsError,
    WrongPasswordError,
    authenticate,
    change_password,
    create_session,
    create_user,
    revoke_session,
    revoke_user_sessions,
)
from app.services.projects.projects import ProjectBusyError
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import ObjectStorage, get_object_storage
from app.services.users.accounts import AccountBusyError, delete_account, update_profile

router = APIRouter(prefix=AUTH_ROUTE_PREFIX, tags=[AUTH_ROUTE_TAG])


def _sign_in(db: Session, request: Request, response: Response, user: User) -> User:
    """Start a session for this browser; a session it already had is ended first, so it never holds two."""
    revoke_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    client_ip = request.client.host if request.client else None
    new = create_session(db, user, client_ip, request.headers.get(USER_AGENT_HEADER))
    set_session_cookie(response, new.token)
    return user


# Create an account and sign it in; the age declaration is required.
# Source: MS3 §1.1.2, §1.4.1.
@router.post(REGISTER_ROUTE, status_code=status.HTTP_201_CREATED, response_model=UserResponse)
def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        user = create_user(db, body.email, body.name, body.password, body.age_group)
    except EmailTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _sign_in(db, request, response, user)


# Sign in with email and password; repeated failures lock the account for a while.
# Source: MS3 §1.1.6.
@router.post(LOGIN_ROUTE, response_model=UserResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        user = authenticate(db, body.email, body.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _sign_in(db, request, response, user)


@router.post(LOGOUT_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Succeeds without a session too, so a browser can always clear its cookie."""
    revoke_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    clear_session_cookie(response)


@router.post(LOGOUT_ALL_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def logout_everywhere(
    response: Response, current: CurrentSession = Depends(get_current_session), db: Session = Depends(get_db)
):
    revoke_user_sessions(db, current.user.id)
    clear_session_cookie(response)


@router.get(ME_ROUTE, response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


# Correct the account's name or email; a new email needs the current password.
# Source: GDPR Art. 16 (rectification); MS3 §1.1.2.
@router.patch(ME_ROUTE, response_model=UserResponse)
def update_me(body: ProfileUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return update_profile(db, user, body.name, body.email, body.current_password)
    except WrongPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except EmailTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# Delete the account and all its projects, then end this browser's session; the audit records are kept.
# Source: MS3 §1.1.2, §1.4.3; GDPR Art. 17.
@router.delete(ME_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    body: AccountDeleteRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    object_storage: ObjectStorage = Depends(get_object_storage),
):
    """A storage failure answers 503 (app-wide handler); the account stays and the request can be repeated."""
    try:
        delete_account(db, storage, object_storage, user, body.password)
    except WrongPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (AccountBusyError, ProjectBusyError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    clear_session_cookie(response)


# Change the password; every other session of the account is signed out.
# Source: MS3 §1.1.6.
@router.put(PASSWORD_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def update_password(
    body: PasswordChangeRequest, current: CurrentSession = Depends(get_current_session), db: Session = Depends(get_db)
):
    try:
        change_password(db, current.user, body.current_password, body.new_password, current.session)
    except WrongPasswordError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
