"""Stand-in for Keycloak in API tests: returns the claims a test sets and records what the API asked for."""
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import AgeGroup
from app.services.auth.identity_provider import (
    IdentityClaims,
    IdentityProvider,
    IdentityProviderError,
    LoginRejectedError,
    LoginRequest,
)

AUTHORIZATION_URL = "http://idp.test/auth"
ACCOUNT_URL = "http://idp.test/account"


def make_claims(**changes) -> IdentityClaims:
    values = dict(
        subject="subject-1",
        email="owner@example.com",
        name="Owner",
        age_group=AgeGroup.ADULT,
        is_admin=False,
        idp_session_id="idp-session-1",
        authenticated_at=datetime.now(timezone.utc),
    )
    values.update(changes)
    return IdentityClaims(**values)


class FakeIdentityProvider(IdentityProvider):
    def __init__(self, claims: Optional[IdentityClaims] = None):
        self.claims = claims or make_claims()
        # Set by a test: raised by complete_login, or every call fails as if Keycloak were down.
        self.rejection: Optional[LoginRejectedError] = None
        self.unavailable = False
        self.completed_logins = []
        self.ended_sessions = []
        self.ended_accounts = []
        self.deleted_accounts = []

    def authorization_url(self, login, *, register=False, reauthenticate=False):
        self._check()
        params = {"state": login.state, "register": register, "reauthenticate": reauthenticate}
        return str(httpx.URL(AUTHORIZATION_URL, params=params))

    def complete_login(self, code, login: LoginRequest):
        self._check()
        self.completed_logins.append((code, login))
        if self.rejection is not None:
            raise self.rejection
        return self.claims

    def account_url(self):
        return ACCOUNT_URL

    def end_session(self, idp_session_id):
        self._check()
        self.ended_sessions.append(idp_session_id)

    def end_all_sessions(self, subject):
        self._check()
        self.ended_accounts.append(subject)

    def delete_user(self, subject):
        self._check()
        self.deleted_accounts.append(subject)

    def _check(self):
        if self.unavailable:
            raise IdentityProviderError("identity provider down")