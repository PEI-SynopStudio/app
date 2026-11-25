"""KeycloakIdentityProvider against a scripted Keycloak (httpx.MockTransport): no network, keys made in the test."""
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import KEYCLOAK_ADMIN_API_SCOPE, AgeGroup, LoginErrorCode
from app.services.auth.identity_provider import (
    IdentityProviderError,
    LoginRejectedError,
    code_challenge,
    new_login_request,
)
from app.services.auth.keycloak import KeycloakIdentityProvider

PUBLIC_URL = "http://localhost:8080"
INTERNAL_URL = "http://keycloak:8080"
REALM = "synopstudio"
CLIENT_ID = "synopstudio-backend"
ISSUER = f"{PUBLIC_URL}/realms/{REALM}"
OIDC = f"/realms/{REALM}/protocol/openid-connect"
REDIRECT_URI = "http://localhost:5173/api/auth/callback"
KEY_ID = "realm-key"


def make_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNING_KEY = make_key()


def public_jwk(key, key_id, use="sig", alg="RS256"):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**jwk, "kid": key_id, "use": use, "alg": alg}


class FakeKeycloak:
    """Answers like Keycloak and records every request."""

    def __init__(self):
        self.requests = []
        self.id_token = None
        self.token_status = 200
        self.admin_status = 204
        # Keycloak also publishes an encryption key; it must be skipped.
        self.keys = [public_jwk(SIGNING_KEY, KEY_ID), public_jwk(make_key(), "enc-key", "enc", "RSA-OAEP")]

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "authorization_endpoint": PUBLIC_URL + OIDC + "/auth",
                "token_endpoint": INTERNAL_URL + OIDC + "/token",
                "jwks_uri": INTERNAL_URL + OIDC + "/certs",
            })
        if path.endswith("/certs"):
            return httpx.Response(200, json={"keys": self.keys})
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["client_credentials"]:
                return httpx.Response(200, json={"access_token": "service-token", "expires_in": 300})
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token})
        if path.startswith("/admin/"):
            return httpx.Response(self.admin_status)
        return httpx.Response(404)

    def admin_requests(self):
        return [request for request in self.requests if request.url.path.startswith("/admin/")]

    def token_forms(self):
        return [parse_qs(r.content.decode()) for r in self.requests if r.url.path.endswith("/token")]


@pytest.fixture
def keycloak():
    return FakeKeycloak()


@pytest.fixture
def provider(keycloak):
    return KeycloakIdentityProvider(
        PUBLIC_URL, INTERNAL_URL, REALM, CLIENT_ID, "secret", REDIRECT_URI, 5, transport=httpx.MockTransport(keycloak)
    )


@pytest.fixture
def login():
    return new_login_request("/app")


def id_token(login, key=SIGNING_KEY, key_id=KEY_ID, algorithm="RS256", **changes):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": CLIENT_ID, "sub": "subject-1", "exp": now + 300, "iat": now, "auth_time": now - 5,
        "nonce": login.nonce, "email": "ana@example.com", "name": "Ana Silva", "age_group": "adult",
        "roles": ["admin"], "sid": "idp-session-1",
    }
    claims = {name: value for name, value in {**claims, **changes}.items() if value is not None}
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": key_id})


def query(url):
    return {name: values[0] for name, values in parse_qs(urlsplit(url).query).items()}


# --- Redirect to the sign-in page (OpenID Connect Core 1.0 §3.1.2.1; RFC 7636) ---

def test_the_sign_in_page_gets_state_nonce_and_a_pkce_challenge(provider, login):
    url = provider.authorization_url(login)

    assert url.startswith(PUBLIC_URL + OIDC + "/auth?")
    params = query(url)
    assert (params["state"], params["nonce"], params["redirect_uri"]) == (login.state, login.nonce, REDIRECT_URI)
    assert (params["code_challenge"], params["code_challenge_method"]) == (code_challenge(login.code_verifier), "S256")
    assert "prompt" not in params
    assert login.code_verifier not in url


def test_registration_and_reauthentication_ask_keycloak_for_their_pages(provider, login):
    assert query(provider.authorization_url(login, register=True))["prompt"] == "create"
    reauth = query(provider.authorization_url(login, reauthenticate=True))
    assert (reauth["prompt"], reauth["max_age"]) == ("login", "0")


def test_the_pkce_verifier_has_a_valid_length(login):
    assert 43 <= len(login.code_verifier) <= 128


# --- Code exchange and ID token checks (OpenID Connect Core 1.0 §3.1.3.7) ---

def test_a_valid_sign_in_returns_the_account(provider, keycloak, login):
    keycloak.id_token = id_token(login)

    claims = provider.complete_login("code-1", login)

    assert (claims.subject, claims.email, claims.name) == ("subject-1", "ana@example.com", "Ana Silva")
    assert (claims.age_group, claims.is_admin, claims.idp_session_id) == (AgeGroup.ADULT, True, "idp-session-1")
    form = keycloak.token_forms()[0]
    assert (form["code"], form["code_verifier"]) == (["code-1"], [login.code_verifier])
    token_request = next(request for request in keycloak.requests if request.url.path.endswith("/token"))
    assert token_request.headers["authorization"].startswith("Basic ")


@pytest.mark.parametrize("changes, code", [
    ({"key": make_key()}, LoginErrorCode.LOGIN_FAILED),
    ({"iss": "http://evil.example/realms/synopstudio"}, LoginErrorCode.LOGIN_FAILED),
    ({"aud": "another-client"}, LoginErrorCode.LOGIN_FAILED),
    ({"exp": int(time.time()) - 60}, LoginErrorCode.LOGIN_FAILED),
    ({"nonce": "another-sign-in"}, LoginErrorCode.LOGIN_FAILED),
    ({"nonce": None}, LoginErrorCode.LOGIN_FAILED),
    ({"auth_time": None}, LoginErrorCode.LOGIN_FAILED),
    ({"key_id": "unknown-key"}, LoginErrorCode.LOGIN_FAILED),
    ({"email": None}, LoginErrorCode.LOGIN_FAILED),
    ({"age_group": None}, LoginErrorCode.AGE_GROUP_MISSING),
    ({"age_group": "under_13"}, LoginErrorCode.AGE_GROUP_MISSING),
])
def test_an_id_token_that_fails_a_check_is_refused(provider, keycloak, login, changes, code):
    keycloak.id_token = id_token(login, **changes)

    with pytest.raises(LoginRejectedError) as rejected:
        provider.complete_login("code-1", login)

    assert rejected.value.code == code


def test_a_token_signed_with_a_shared_secret_is_refused(provider, keycloak, login):
    keycloak.id_token = id_token(login, key="a-shared-secret-long-enough-for-hs256", algorithm="HS256")

    with pytest.raises(LoginRejectedError):
        provider.complete_login("code-1", login)


def test_a_rotated_realm_key_is_fetched_again(provider, keycloak, login):
    keycloak.id_token = id_token(login)
    provider.complete_login("code-1", login)
    new_key = make_key()
    keycloak.keys = [public_jwk(new_key, "new-key")]
    keycloak.id_token = id_token(login, key=new_key, key_id="new-key")

    assert provider.complete_login("code-2", login).subject == "subject-1"


def test_a_code_keycloak_refuses_is_a_failed_sign_in(provider, keycloak, login):
    keycloak.token_status = 400

    with pytest.raises(LoginRejectedError) as rejected:
        provider.complete_login("used-code", login)

    assert rejected.value.code == LoginErrorCode.LOGIN_FAILED


def test_keycloak_out_of_reach_is_reported_as_unavailable(login):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    provider = KeycloakIdentityProvider(
        PUBLIC_URL, INTERNAL_URL, REALM, CLIENT_ID, "secret", REDIRECT_URI, 5, transport=httpx.MockTransport(refuse)
    )

    with pytest.raises(IdentityProviderError):
        provider.authorization_url(login)


# --- Admin API: sessions and account deletion (Keycloak 26.8.2 audience check) ---

def test_admin_calls_use_a_service_account_token_with_the_admin_api_scope(provider, keycloak):
    provider.end_session("idp-session-1")
    provider.end_all_sessions("subject-1")
    provider.delete_user("subject-1")

    calls = [(request.method, request.url.path) for request in keycloak.admin_requests()]
    assert calls == [
        ("DELETE", f"/admin/realms/{REALM}/sessions/idp-session-1"),
        ("POST", f"/admin/realms/{REALM}/users/subject-1/logout"),
        ("DELETE", f"/admin/realms/{REALM}/users/subject-1"),
    ]
    assert all(request.headers["authorization"] == "Bearer service-token" for request in keycloak.admin_requests())
    service_token_requests = [form for form in keycloak.token_forms() if form["grant_type"] == ["client_credentials"]]
    assert service_token_requests == [{"grant_type": ["client_credentials"], "scope": [KEYCLOAK_ADMIN_API_SCOPE]}]


def test_an_account_or_session_keycloak_no_longer_has_counts_as_done(provider, keycloak):
    keycloak.admin_status = 404

    provider.delete_user("subject-1")
    provider.end_session("idp-session-1")


@pytest.mark.parametrize("status", [401, 403, 503])
def test_an_admin_call_keycloak_refuses_is_reported_as_unavailable(provider, keycloak, status):
    keycloak.admin_status = status

    with pytest.raises(IdentityProviderError):
        provider.delete_user("subject-1")


def test_identifiers_cannot_change_the_admin_path(provider, keycloak):
    provider.delete_user("../../realms/master?x=1")

    assert keycloak.admin_requests()[0].url.raw_path.decode() == (
        f"/admin/realms/{REALM}/users/..%2F..%2Frealms%2Fmaster%3Fx%3D1"
    )


def test_the_account_page_is_on_the_public_address(provider):
    assert provider.account_url() == f"{PUBLIC_URL}/realms/{REALM}/account"
