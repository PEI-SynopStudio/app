import hmac
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import httpx
import jwt

from app.core.config import (
    ADMIN_ROLE,
    ADMIN_TOKEN_REFRESH_MARGIN_SECONDS,
    AUTH_ROUTE_PREFIX,
    AUTHORIZATION_HEADER,
    BEARER_TOKEN_FORMAT,
    CALLBACK_ROUTE,
    CLAIM_AGE_GROUP,
    CLAIM_AUTH_TIME,
    CLAIM_EMAIL,
    CLAIM_NAME,
    CLAIM_NONCE,
    CLAIM_ROLES,
    CLAIM_SESSION_ID,
    CLAIM_SUBJECT,
    ERROR_IDENTITY_PROVIDER_UNAVAILABLE,
    ID_TOKEN_ALGORITHMS,
    ID_TOKEN_REQUIRED_CLAIMS,
    KEYCLOAK_ACCOUNT_PATH,
    KEYCLOAK_ADMIN_SESSION_PATH,
    KEYCLOAK_ADMIN_USER_LOGOUT_PATH,
    KEYCLOAK_ADMIN_USER_PATH,
    KEYCLOAK_DISCOVERY_PATH,
    KEYCLOAK_ISSUER_PATH,
    LOGIN_REASON_AGE_GROUP,
    LOGIN_REASON_CODE_REFUSED,
    LOGIN_REASON_INVALID_ID_TOKEN,
    LOGIN_REASON_MISSING_EMAIL,
    LOGIN_REASON_MISSING_ID_TOKEN,
    LOGIN_REASON_NONCE_MISMATCH,
    LOGIN_REASON_UNKNOWN_KEY,
    OIDC_GRANT_AUTHORIZATION_CODE,
    OIDC_GRANT_CLIENT_CREDENTIALS,
    OIDC_PROMPT_CREATE,
    OIDC_PROMPT_LOGIN,
    OIDC_REAUTH_MAX_AGE,
    OIDC_RESPONSE_TYPE,
    OIDC_SCOPES,
    PKCE_METHOD,
    URL_SEGMENT_SAFE_CHARACTERS,
    AgeGroup,
    LoginErrorCode,
    get_settings,
)
from app.services.auth.identity_provider import (
    IdentityClaims,
    IdentityProvider,
    IdentityProviderError,
    LoginRejectedError,
    LoginRequest,
    code_challenge,
)


class KeycloakIdentityProvider(IdentityProvider):
    """Keycloak through OpenID Connect (sign-in) and its Admin API (sessions, account deletion).

    The browser goes to the public address; the backend calls Keycloak on the internal one. Keycloak returns
    the endpoints for the address it was asked on, so the discovery document is read from the internal one.
    """

    def __init__(
        self,
        public_url: str,
        internal_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        timeout_seconds: float,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._public_url = public_url
        self._internal_url = internal_url
        self._realm = realm
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._issuer = public_url + KEYCLOAK_ISSUER_PATH.format(realm=realm)
        # transport replaces the network in tests (httpx.MockTransport).
        self._http = httpx.Client(timeout=timeout_seconds, transport=transport)
        # Requests run in FastAPI's thread pool; the caches below are filled by one thread at a time.
        self._lock = threading.RLock()
        self._endpoints: Optional[Dict[str, Any]] = None
        self._keys: Optional[jwt.PyJWKSet] = None
        self._admin_token: Optional[str] = None
        self._admin_token_renew_at = 0.0

    # Send the browser to Keycloak with state, nonce and the PKCE challenge.
    # Source: OpenID Connect Core 1.0 §3.1.2.1; RFC 7636 §4.3; Keycloak 26.1 prompt=create.
    def authorization_url(self, login: LoginRequest, *, register: bool = False, reauthenticate: bool = False) -> str:
        params = {
            "client_id": self._client_id,
            "response_type": OIDC_RESPONSE_TYPE,
            "scope": OIDC_SCOPES,
            "redirect_uri": self._redirect_uri,
            "state": login.state,
            "nonce": login.nonce,
            "code_challenge": code_challenge(login.code_verifier),
            "code_challenge_method": PKCE_METHOD,
        }
        if register:
            params["prompt"] = OIDC_PROMPT_CREATE
        elif reauthenticate:
            params["prompt"] = OIDC_PROMPT_LOGIN
            params["max_age"] = OIDC_REAUTH_MAX_AGE
        return str(httpx.URL(self._endpoint("authorization_endpoint"), params=params))

    # Exchange the authorization code (with the PKCE verifier) and verify the ID token it returns.
    # Source: OpenID Connect Core 1.0 §3.1.3; RFC 7636 §4.5.
    def complete_login(self, code: str, login: LoginRequest) -> IdentityClaims:
        response = self._send(
            self._http.post,
            self._endpoint("token_endpoint"),
            data={
                "grant_type": OIDC_GRANT_AUTHORIZATION_CODE,
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": login.code_verifier,
            },
            auth=(self._client_id, self._client_secret),
        )
        # A used, expired or forged code is a failed sign-in, not an outage.
        if response.is_client_error:
            raise LoginRejectedError(LoginErrorCode.LOGIN_FAILED, LOGIN_REASON_CODE_REFUSED)
        return self.verify_id_token(self._json(response).get("id_token"), login.nonce)

    # Check signature, issuer, audience, expiry and nonce of the ID token, then read the account from it.
    # Source: OpenID Connect Core 1.0 §3.1.3.7.
    def verify_id_token(self, id_token: Optional[str], nonce: str) -> IdentityClaims:
        if not id_token:
            raise LoginRejectedError(LoginErrorCode.LOGIN_FAILED, LOGIN_REASON_MISSING_ID_TOKEN)
        try:
            claims = jwt.decode(
                id_token,
                self._signing_key(id_token),
                algorithms=list(ID_TOKEN_ALGORITHMS),
                audience=self._client_id,
                issuer=self._issuer,
                options={"require": list(ID_TOKEN_REQUIRED_CLAIMS)},
            )
        except jwt.InvalidTokenError as exc:
            raise LoginRejectedError(
                LoginErrorCode.LOGIN_FAILED, LOGIN_REASON_INVALID_ID_TOKEN.format(error=exc)
            ) from exc
        if not hmac.compare_digest(str(claims[CLAIM_NONCE]), nonce):
            raise LoginRejectedError(LoginErrorCode.LOGIN_FAILED, LOGIN_REASON_NONCE_MISMATCH)
        return _identity(claims)

    def account_url(self) -> str:
        return self._public_url + KEYCLOAK_ACCOUNT_PATH.format(realm=self._realm)

    def end_session(self, idp_session_id: str) -> None:
        path = KEYCLOAK_ADMIN_SESSION_PATH.format(realm=_segment(self._realm), session_id=_segment(idp_session_id))
        self._admin(self._http.delete, path)

    def end_all_sessions(self, subject: str) -> None:
        path = KEYCLOAK_ADMIN_USER_LOGOUT_PATH.format(realm=_segment(self._realm), user_id=_segment(subject))
        self._admin(self._http.post, path)

    def delete_user(self, subject: str) -> None:
        path = KEYCLOAK_ADMIN_USER_PATH.format(realm=_segment(self._realm), user_id=_segment(subject))
        self._admin(self._http.delete, path)

    def _endpoint(self, name: str) -> str:
        """Read once from the discovery document; a failed read is retried on the next call."""
        with self._lock:
            if self._endpoints is None:
                url = self._internal_url + KEYCLOAK_DISCOVERY_PATH.format(realm=self._realm)
                self._endpoints = self._json(self._checked(self._send(self._http.get, url)))
            try:
                return self._endpoints[name]
            except KeyError as exc:
                raise IdentityProviderError(ERROR_IDENTITY_PROVIDER_UNAVAILABLE) from exc

    def _signing_key(self, id_token: str) -> Any:
        """The realm key named in the token header; the key set is read again once, in case Keycloak rotated it."""
        key_id = jwt.get_unverified_header(id_token).get("kid")
        for refresh in (False, True):
            keys = self._key_set(refresh)
            try:
                return keys[key_id].key
            except KeyError:
                continue
        raise jwt.InvalidTokenError(LOGIN_REASON_UNKNOWN_KEY)

    def _key_set(self, refresh: bool) -> jwt.PyJWKSet:
        with self._lock:
            if self._keys is None or refresh:
                response = self._checked(self._send(self._http.get, self._endpoint("jwks_uri")))
                try:
                    self._keys = jwt.PyJWKSet.from_dict(self._json(response))
                except jwt.PyJWKSetError as exc:
                    raise IdentityProviderError(ERROR_IDENTITY_PROVIDER_UNAVAILABLE) from exc
            return self._keys

    # Call the Admin API as the client's service account (realm-management: manage-users).
    # Source: Keycloak Admin REST API; RFC 6749 §4.4 (client credentials).
    def _admin(self, send: Callable[..., httpx.Response], path: str) -> None:
        """A missing user or session counts as done, so repeating a call after a partial failure succeeds."""
        response = self._send(send, self._internal_url + path, headers=self._admin_headers())
        if response.status_code == httpx.codes.NOT_FOUND:
            return
        if response.status_code == httpx.codes.UNAUTHORIZED:
            # Revoked early: the next call asks for a new token.
            with self._lock:
                self._admin_token = None
        self._checked(response)

    def _admin_headers(self) -> Dict[str, str]:
        with self._lock:
            if self._admin_token is None or time.monotonic() >= self._admin_token_renew_at:
                response = self._send(
                    self._http.post,
                    self._endpoint("token_endpoint"),
                    data={"grant_type": OIDC_GRANT_CLIENT_CREDENTIALS},
                    auth=(self._client_id, self._client_secret),
                )
                tokens = self._json(self._checked(response))
                try:
                    self._admin_token = tokens["access_token"]
                    lifetime = float(tokens["expires_in"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise IdentityProviderError(ERROR_IDENTITY_PROVIDER_UNAVAILABLE) from exc
                self._admin_token_renew_at = time.monotonic() + lifetime - ADMIN_TOKEN_REFRESH_MARGIN_SECONDS
            return {AUTHORIZATION_HEADER: BEARER_TOKEN_FORMAT.format(token=self._admin_token)}

    @staticmethod
    def _send(send: Callable[..., httpx.Response], url: str, **kwargs: Any) -> httpx.Response:
        """Network failures and server errors mean Keycloak is unavailable; client errors are left to the caller."""
        try:
            response = send(url, **kwargs)
        except httpx.HTTPError as exc:
            raise IdentityProviderError(ERROR_IDENTITY_PROVIDER_UNAVAILABLE) from exc
        if response.is_server_error:
            raise IdentityProviderError(ERROR_IDENTITY_PROVIDER_UNAVAILABLE)
        return response

    @staticmethod
    def _checked(response: httpx.Response) -> httpx.Response:
        """Outside the code exchange a client error is a configuration problem, reported as unavailable."""
        if response.is_error:
            raise IdentityProviderError(ERROR_IDENTITY_PROVIDER_UNAVAILABLE)
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise IdentityProviderError(ERROR_IDENTITY_PROVIDER_UNAVAILABLE) from exc
        if not isinstance(body, dict):
            raise IdentityProviderError(ERROR_IDENTITY_PROVIDER_UNAVAILABLE)
        return body


def _segment(value: str) -> str:
    """Percent-encode a value placed in a URL path, so it stays one segment whatever it contains."""
    return quote(value, safe=URL_SEGMENT_SAFE_CHARACTERS)


def _identity(claims: Dict[str, Any]) -> IdentityClaims:
    """Accounts without email or without a valid age group are refused (MS3 §1.1.2, §1.4.1)."""
    email = claims.get(CLAIM_EMAIL)
    if not email:
        raise LoginRejectedError(LoginErrorCode.LOGIN_FAILED, LOGIN_REASON_MISSING_EMAIL)
    try:
        age_group = AgeGroup(claims.get(CLAIM_AGE_GROUP))
    except ValueError as exc:
        raise LoginRejectedError(LoginErrorCode.AGE_GROUP_MISSING, LOGIN_REASON_AGE_GROUP) from exc
    return IdentityClaims(
        subject=claims[CLAIM_SUBJECT],
        email=email,
        name=claims.get(CLAIM_NAME) or email,
        age_group=age_group,
        is_admin=ADMIN_ROLE in (claims.get(CLAIM_ROLES) or []),
        idp_session_id=claims.get(CLAIM_SESSION_ID),
        authenticated_at=datetime.fromtimestamp(claims[CLAIM_AUTH_TIME], tz=timezone.utc),
    )


@lru_cache
def get_identity_provider() -> IdentityProvider:
    """FastAPI dependency; tests replace it with FakeIdentityProvider."""
    settings = get_settings()
    return KeycloakIdentityProvider(
        public_url=settings.keycloak_public_url,
        internal_url=settings.keycloak_internal_url,
        realm=settings.keycloak_realm,
        client_id=settings.keycloak_client_id,
        client_secret=settings.keycloak_client_secret,
        redirect_uri=settings.app_public_url + settings.api_public_path + AUTH_ROUTE_PREFIX + CALLBACK_ROUTE,
        timeout_seconds=settings.idp_timeout_seconds,
    )