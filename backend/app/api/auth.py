import base64
import binascii
import hmac
import json
import logging
from dataclasses import asdict
from typing import Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CurrentSession,
    clear_session_cookie,
    get_current_session,
    get_current_user,
    set_session_cookie,
)
from app.core.config import (
    ACCOUNT_ROUTE,
    AUTH_ROUTE_PREFIX,
    AUTH_ROUTE_TAG,
    CALLBACK_ROUTE,
    FRONTEND_DEFAULT_NEXT_PATH,
    FRONTEND_LOGIN_PATH,
    LOG_IDENTITY_PROVIDER_LOGOUT_FAILED,
    LOG_IDENTITY_PROVIDER_UNAVAILABLE,
    LOG_LOGIN_REJECTED,
    LOGIN_COOKIE_NAME,
    LOGIN_ERROR_QUERY_PARAM,
    LOGIN_REASON_RETURNED_ERROR,
    LOGIN_REASON_STATE_MISMATCH,
    LOGIN_ROUTE,
    LOGOUT_ALL_ROUTE,
    LOGOUT_ROUTE,
    ME_ROUTE,
    NEXT_PATH_FORBIDDEN_CHARACTERS,
    NEXT_PATH_PREFIX,
    NEXT_QUERY_PARAM,
    REAUTHENTICATION_REQUIRED_CODE,
    REGISTER_ROUTE,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
    SESSION_COOKIE_SAMESITE,
    URL_MAX_LENGTH,
    USER_AGENT_HEADER,
    LoginErrorCode,
    get_settings,
)
from app.database.models import User
from app.database.session import get_db
from app.schemas.auth import UserResponse
from app.services.auth.auth import (
    create_session,
    is_recently_authenticated,
    provision_user,
    revoke_session,
    revoke_user_sessions,
)
from app.services.auth.identity_provider import (
    IdentityClaims,
    IdentityProvider,
    IdentityProviderError,
    LoginRejectedError,
    LoginRequest,
    new_login_request,
)
from app.services.auth.keycloak import get_identity_provider
from app.services.projects.projects import ProjectBusyError
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import ObjectStorage, get_object_storage
from app.services.users.accounts import AccountBusyError, delete_account

logger = logging.getLogger(__name__)

router = APIRouter(prefix=AUTH_ROUTE_PREFIX, tags=[AUTH_ROUTE_TAG])


# Send the browser to the Keycloak sign-in page; with reauth it must enter the password again.
# Source: OpenID Connect Core 1.0 §3.1.2; architecture §2; T4.25 (re-authentication before deleting the account).
@router.get(LOGIN_ROUTE, status_code=status.HTTP_302_FOUND, response_class=RedirectResponse)
def login(
    next_path: Optional[str] = Query(None, alias=NEXT_QUERY_PARAM),
    reauth: bool = False,
    identity_provider: IdentityProvider = Depends(get_identity_provider),
):
    return _start_login(identity_provider, next_path, reauthenticate=reauth)


# Send the browser to the Keycloak sign-up page, which asks for name, email, password, age group and the terms.
# Source: MS3 §1.1.2, §1.4.1; Keycloak 26.1 prompt=create.
@router.get(REGISTER_ROUTE, status_code=status.HTTP_302_FOUND, response_class=RedirectResponse)
def register(
    next_path: Optional[str] = Query(None, alias=NEXT_QUERY_PARAM),
    identity_provider: IdentityProvider = Depends(get_identity_provider),
):
    return _start_login(identity_provider, next_path, register=True)


# Finish the sign-in: check the state, exchange the code, create or refresh the account and open a session.
# Source: OpenID Connect Core 1.0 §3.1.2.5–§3.1.3; MS3 §1.1.6.
@router.get(CALLBACK_ROUTE, status_code=status.HTTP_302_FOUND, response_class=RedirectResponse)
def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
    identity_provider: IdentityProvider = Depends(get_identity_provider),
):
    """Every failure sends the browser back to the login page with a code; the reason is only logged."""
    login_request = _read_login_cookie(request)
    if login_request is None or state is None or not hmac.compare_digest(state, login_request.state):
        logger.warning(LOG_LOGIN_REJECTED, LOGIN_REASON_STATE_MISMATCH)
        return _login_failed(LoginErrorCode.LOGIN_FAILED)
    if error is not None or code is None:
        # The user went back from the Keycloak page (access_denied) or Keycloak refused the request.
        logger.warning(LOG_LOGIN_REJECTED, LOGIN_REASON_RETURNED_ERROR.format(error=error))
        return _login_failed(LoginErrorCode.LOGIN_CANCELLED)
    try:
        claims = identity_provider.complete_login(code, login_request)
        user = provision_user(db, claims)
    except LoginRejectedError as exc:
        logger.warning(LOG_LOGIN_REJECTED, exc)
        return _login_failed(exc.code)
    except IdentityProviderError:
        logger.error(LOG_IDENTITY_PROVIDER_UNAVAILABLE, exc_info=True)
        return _login_failed(LoginErrorCode.IDENTITY_PROVIDER_UNAVAILABLE)
    # Checked again: the cookie came back from the browser.
    next_url = _app_url(_safe_next_path(login_request.next_path))
    response = RedirectResponse(next_url, status_code=status.HTTP_302_FOUND)
    _start_session(db, request, response, user, claims)
    _clear_login_cookie(response)
    return response


# Sign out this browser here and at Keycloak, so the next sign-in asks for the password again.
# Source: MS3 §1.1.6; OpenID Connect session management (Keycloak Admin API).
@router.post(LOGOUT_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    identity_provider: IdentityProvider = Depends(get_identity_provider),
):
    """Succeeds without a session too, and when Keycloak is down: the session here is already gone."""
    idp_session_id = revoke_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    clear_session_cookie(response)
    if idp_session_id is not None:
        try:
            identity_provider.end_session(idp_session_id)
        except IdentityProviderError:
            logger.warning(LOG_IDENTITY_PROVIDER_LOGOUT_FAILED, exc_info=True)


@router.post(LOGOUT_ALL_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def logout_everywhere(
    response: Response,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    identity_provider: IdentityProvider = Depends(get_identity_provider),
):
    """Ends every session of the account, here and at Keycloak (other browsers and devices too)."""
    revoke_user_sessions(db, current.user.id)
    clear_session_cookie(response)
    if current.user.subject is not None:
        try:
            identity_provider.end_all_sessions(current.user.subject)
        except IdentityProviderError:
            logger.warning(LOG_IDENTITY_PROVIDER_LOGOUT_FAILED, exc_info=True)


@router.get(ME_ROUTE, response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


# Name, email and password are changed on the Keycloak account page.
# Source: GDPR Art. 16 (rectification); architecture §2.
@router.get(ACCOUNT_ROUTE, status_code=status.HTTP_302_FOUND, response_class=RedirectResponse)
def account(identity_provider: IdentityProvider = Depends(get_identity_provider)):
    return RedirectResponse(identity_provider.account_url(), status_code=status.HTTP_302_FOUND)


# Delete the account and all its projects, here and at Keycloak; the audit records are kept.
# Source: MS3 §1.1.2, §1.4.3; GDPR Art. 17; T4.25 (a recent sign-in is required).
@router.delete(ME_ROUTE, status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    response: Response,
    current: CurrentSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    object_storage: ObjectStorage = Depends(get_object_storage),
    identity_provider: IdentityProvider = Depends(get_identity_provider),
):
    """403 with REAUTHENTICATION_REQUIRED_CODE asks the frontend to sign in again (/auth/login?reauth=true).

    A storage or Keycloak failure answers 503 (app-wide handlers); the account stays and the request can be repeated.
    """
    if not is_recently_authenticated(current.session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=REAUTHENTICATION_REQUIRED_CODE)
    try:
        delete_account(db, storage, object_storage, identity_provider, current.user)
    except (AccountBusyError, ProjectBusyError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    clear_session_cookie(response)


def _start_login(
    identity_provider: IdentityProvider,
    next_path: Optional[str],
    *,
    register: bool = False,
    reauthenticate: bool = False,
) -> RedirectResponse:
    login_request = new_login_request(_safe_next_path(next_path))
    try:
        url = identity_provider.authorization_url(login_request, register=register, reauthenticate=reauthenticate)
    except IdentityProviderError:
        logger.error(LOG_IDENTITY_PROVIDER_UNAVAILABLE, exc_info=True)
        return _login_failed(LoginErrorCode.IDENTITY_PROVIDER_UNAVAILABLE)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    _set_login_cookie(response, login_request)
    return response


def _start_session(db: Session, request: Request, response: Response, user: User, claims: IdentityClaims) -> None:
    """A session this browser already had is ended first, so it never holds two."""
    revoke_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    client_ip = request.client.host if request.client else None
    new = create_session(
        db,
        user,
        client_ip,
        request.headers.get(USER_AGENT_HEADER),
        idp_session_id=claims.idp_session_id,
        authenticated_at=claims.authenticated_at,
    )
    set_session_cookie(response, new.token)


def _safe_next_path(next_path: Optional[str]) -> str:
    """A path on this site, or the default page: no scheme, no host, no backslash or control characters."""
    if (
        not next_path
        or len(next_path) > URL_MAX_LENGTH
        or not next_path.startswith(NEXT_PATH_PREFIX)
        or any(char in NEXT_PATH_FORBIDDEN_CHARACTERS or not char.isprintable() or char.isspace() for char in next_path)
    ):
        return FRONTEND_DEFAULT_NEXT_PATH
    parts = urlsplit(next_path)
    if parts.scheme or parts.netloc:
        return FRONTEND_DEFAULT_NEXT_PATH
    return next_path


def _app_url(path: str) -> str:
    return get_settings().app_public_url + path


def _login_failed(code: LoginErrorCode) -> RedirectResponse:
    url = httpx.URL(_app_url(FRONTEND_LOGIN_PATH), params={LOGIN_ERROR_QUERY_PARAM: code.value})
    response = RedirectResponse(str(url), status_code=status.HTTP_302_FOUND)
    _clear_login_cookie(response)
    return response


def _set_login_cookie(response: Response, login_request: LoginRequest) -> None:
    """httpOnly and short-lived; SameSite=Lax still sends it on the top-level redirect back from Keycloak."""
    settings = get_settings()
    value = base64.urlsafe_b64encode(json.dumps(asdict(login_request)).encode()).decode()
    response.set_cookie(
        LOGIN_COOKIE_NAME,
        value,
        max_age=settings.login_request_ttl_seconds,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
        secure=settings.session_cookie_secure,
    )


def _read_login_cookie(request: Request) -> Optional[LoginRequest]:
    value = request.cookies.get(LOGIN_COOKIE_NAME)
    if not value:
        return None
    try:
        login_request = LoginRequest(**json.loads(base64.urlsafe_b64decode(value.encode())))
    except (binascii.Error, ValueError, TypeError):
        return None
    if not all(isinstance(field, str) for field in asdict(login_request).values()):
        return None
    return login_request


def _clear_login_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        LOGIN_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
        secure=settings.session_cookie_secure,
    )
