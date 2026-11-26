import base64
import hashlib
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.core.config import (
    BASE64_PADDING,
    LOGIN_NONCE_BYTES,
    LOGIN_STATE_BYTES,
    PKCE_VERIFIER_BYTES,
    AgeGroup,
    LoginErrorCode,
)


class IdentityProviderError(Exception):
    """The identity provider is unreachable or failed; the API answers 503 and the action can be repeated."""


class LoginRejectedError(Exception):
    """A sign-in came back from the identity provider but cannot be accepted; the browser returns to the login page."""

    def __init__(self, code: LoginErrorCode, reason: str):
        super().__init__(reason)
        self.code = code


@dataclass(frozen=True)
class LoginRequest:
    """Kept in the login cookie between the redirect to the identity provider and the callback.

    state ties the callback to this browser (CSRF), nonce ties the ID token to this sign-in (replay),
    and code_verifier proves that whoever exchanges the code started the sign-in (PKCE).
    """

    state: str
    nonce: str
    code_verifier: str
    next_path: str


@dataclass(frozen=True)
class IdentityClaims:
    """The verified identity of one sign-in, read from the ID token."""

    subject: str
    email: str
    name: str
    age_group: AgeGroup
    is_admin: bool
    # The identity provider session ("sid"), ended there when the user signs out.
    idp_session_id: Optional[str]
    # When the user last entered a password at the identity provider ("auth_time").
    authenticated_at: datetime


class IdentityProvider(ABC):
    """Accounts and sign-in live in the identity provider; KeycloakIdentityProvider implements it."""

    @abstractmethod
    def authorization_url(self, login: LoginRequest, *, register: bool = False, reauthenticate: bool = False) -> str:
        """Where to send the browser; register opens the sign-up page, reauthenticate always asks for the password."""

    @abstractmethod
    def complete_login(self, code: str, login: LoginRequest) -> IdentityClaims:
        """Exchange the code of the callback and verify the ID token; LoginRejectedError if it cannot be accepted."""

    @abstractmethod
    def account_url(self) -> str:
        """The page where users change their name, email and password."""

    @abstractmethod
    def end_session(self, idp_session_id: str) -> None:
        """End one session at the identity provider; an unknown session counts as ended."""

    @abstractmethod
    def end_all_sessions(self, subject: str) -> None:
        """End every session of the account at the identity provider."""

    @abstractmethod
    def delete_user(self, subject: str) -> None:
        """Delete the account at the identity provider; an unknown account counts as deleted."""


# Start a sign-in with a fresh random state, nonce and PKCE verifier.
def new_login_request(next_path: str) -> LoginRequest:
    return LoginRequest(
        state=secrets.token_urlsafe(LOGIN_STATE_BYTES),
        nonce=secrets.token_urlsafe(LOGIN_NONCE_BYTES),
        code_verifier=secrets.token_urlsafe(PKCE_VERIFIER_BYTES),
        next_path=next_path,
    )


# The PKCE challenge sent with the redirect; the verifier itself only travels in the code exchange.
def code_challenge(code_verifier: str) -> str:
    """Base64url of the SHA-256 of the verifier, without padding."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip(BASE64_PADDING)