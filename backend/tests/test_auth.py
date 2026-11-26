import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.config import (
    FRONTEND_DEFAULT_NEXT_PATH,
    FRONTEND_LOGIN_PATH,
    LOGIN_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SAMESITE,
    AgeGroup,
    LoginErrorCode,
    get_settings,
)
from app.database.base import utc_now
from app.database.models import AuthSession, User
from app.main import app
from app.services.auth.identity_provider import LoginRejectedError
from conftest import add_user, sign_in
from fake_identity_provider import ACCOUNT_URL, AUTHORIZATION_URL, make_claims

PROJECT_BODY = {
    "title": "Debate",
    "author": "University of Aveiro",
    "speakers": ["Ana"],
    "recording_date": "2026-10-01",
    "license_type": "creative_commons",
    "copyright_notice": "CC BY 4.0",
    "licence_confirmed": True,
    "authorship_confirmed": True,
}


@pytest.fixture
def client(db_override, identity_provider):
    """A browser with no session yet; Keycloak is the fake from conftest."""
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def session_count(db):
    return db.scalar(select(func.count()).select_from(AuthSession))


def stored_session(db, token):
    """The database row behind this session token."""
    db.expire_all()
    return db.scalar(select(AuthSession).where(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))


def lifetime():
    return timedelta(seconds=get_settings().session_ttl_seconds)


def set_expiry(db, expires_at):
    db.execute(update(AuthSession).values(expires_at=expires_at))
    db.commit()


def query(location):
    return {name: values[0] for name, values in parse_qs(urlsplit(location).query).items()}


def app_url(path):
    return get_settings().app_public_url + path


def login_error(response):
    """The error code of a redirect back to the frontend login page."""
    assert response.status_code == 302
    assert response.headers["location"].startswith(app_url(FRONTEND_LOGIN_PATH))
    return query(response.headers["location"])["error"]


def start_login(client, path="/auth/login", **params):
    """The redirect to Keycloak; the browser keeps the login cookie."""
    response = client.get(path, params=params)
    assert response.status_code == 302
    return response


def finish_login(client, code="code-1", **params):
    """Come back from Keycloak with the state of the sign-in this browser started."""
    started = start_login(client, **params)
    return client.get("/auth/callback", params={"code": code, "state": query(started.headers["location"])["state"]})


# --- Starting a sign-in: redirect to Keycloak (architecture §2) ---

def test_signing_in_sends_the_browser_to_keycloak_with_a_short_lived_login_cookie(client):
    response = start_login(client)

    assert response.headers["location"].startswith(AUTHORIZATION_URL)
    assert query(response.headers["location"])["register"] == "false"
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(LOGIN_COOKIE_NAME)
    assert "httponly" in cookie
    assert f"samesite={SESSION_COOKIE_SAMESITE}" in cookie
    assert f"max-age={get_settings().login_request_ttl_seconds}" in cookie


def test_each_sign_in_gets_its_own_state(client):
    first = query(start_login(client).headers["location"])["state"]
    second = query(start_login(client).headers["location"])["state"]

    assert first != second


def test_signing_up_opens_the_keycloak_registration_page(client):
    assert query(start_login(client, "/auth/register").headers["location"])["register"] == "true"


def test_reauthentication_asks_keycloak_for_the_password_again(client):
    assert query(start_login(client, reauth="true").headers["location"])["reauthenticate"] == "true"


def test_keycloak_down_sends_the_browser_back_with_an_error(client, identity_provider):
    identity_provider.unavailable = True

    assert login_error(client.get("/auth/login")) == LoginErrorCode.IDENTITY_PROVIDER_UNAVAILABLE.value


# --- Finishing a sign-in: callback (OpenID Connect Core 1.0 §3.1.2.5; MS3 §1.1.6) ---

@pytest.mark.parametrize("age_group", list(AgeGroup))
def test_the_callback_creates_the_account_and_signs_the_user_in(client, db, identity_provider, age_group):
    identity_provider.claims = make_claims(email="Ana@Example.com", name="Ana", age_group=age_group)

    response = finish_login(client, next="/app/projects")

    assert response.status_code == 302
    assert response.headers["location"] == app_url("/app/projects")
    me = client.get("/auth/me").json()
    assert (me["email"], me["name"], me["age_group"]) == ("ana@example.com", "Ana", age_group.value)
    assert db.scalar(select(User)).subject == "subject-1"
    session = stored_session(db, client.cookies.get(SESSION_COOKIE_NAME))
    assert session.idp_session_id == "idp-session-1"
    assert session.authenticated_at == identity_provider.claims.authenticated_at
    assert identity_provider.completed_logins[0][0] == "code-1"


def test_the_callback_clears_the_login_cookie_and_sets_a_protected_session_cookie(client):
    response = finish_login(client)

    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(cookie for cookie in cookies if cookie.startswith(SESSION_COOKIE_NAME)).lower()
    login_cookie = next(cookie for cookie in cookies if cookie.startswith(LOGIN_COOKIE_NAME)).lower()
    assert "httponly" in session_cookie
    assert f"samesite={SESSION_COOKIE_SAMESITE}" in session_cookie
    assert "max-age=0" in login_cookie


def test_the_session_token_is_only_stored_hashed(client, db):
    finish_login(client)

    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert stored_session(db, token).token_hash != token


@pytest.mark.parametrize("next_path", [
    None,
    "app",
    "//evil.example",
    "https://evil.example",
    "/\\evil.example",
    "/\t/evil.example",
    "/" + "a" * 3000,
])
def test_the_callback_never_redirects_to_another_site(client, next_path):
    params = {} if next_path is None else {"next": next_path}

    assert finish_login(client, **params).headers["location"] == app_url(FRONTEND_DEFAULT_NEXT_PATH)


@pytest.mark.parametrize("state", [None, "forged-state"])
def test_a_callback_without_the_state_of_this_browser_is_refused(client, db, identity_provider, state):
    start_login(client)
    params = {"code": "code-1"} if state is None else {"code": "code-1", "state": state}

    assert login_error(client.get("/auth/callback", params=params)) == LoginErrorCode.LOGIN_FAILED.value
    assert identity_provider.completed_logins == []
    assert session_count(db) == 0


def test_a_callback_from_another_browser_is_refused(client, identity_provider):
    state = query(start_login(client).headers["location"])["state"]
    other_browser = TestClient(app, follow_redirects=False)

    response = other_browser.get("/auth/callback", params={"code": "code-1", "state": state})

    assert login_error(response) == LoginErrorCode.LOGIN_FAILED.value
    assert identity_provider.completed_logins == []


def test_a_forged_login_cookie_is_refused(client, identity_provider):
    client.cookies.set(LOGIN_COOKIE_NAME, "not-base64-json")

    response = client.get("/auth/callback", params={"code": "code-1", "state": "x"})

    assert login_error(response) == LoginErrorCode.LOGIN_FAILED.value


def test_going_back_from_the_keycloak_page_is_a_cancelled_sign_in(client, db):
    state = query(start_login(client).headers["location"])["state"]

    response = client.get("/auth/callback", params={"error": "access_denied", "state": state})

    assert login_error(response) == LoginErrorCode.LOGIN_CANCELLED.value
    assert session_count(db) == 0


@pytest.mark.parametrize("code", list(LoginErrorCode))
def test_a_sign_in_keycloak_or_the_backend_refuses_opens_no_session(client, db, identity_provider, code):
    identity_provider.rejection = LoginRejectedError(code, "refused in the test")

    assert login_error(finish_login(client)) == code.value
    assert session_count(db) == 0
    assert db.scalar(select(func.count()).select_from(User)) == 0


def test_keycloak_down_during_the_callback_opens_no_session(client, db, identity_provider):
    state = query(start_login(client).headers["location"])["state"]
    identity_provider.unavailable = True

    response = client.get("/auth/callback", params={"code": "code-1", "state": state})

    assert login_error(response) == LoginErrorCode.IDENTITY_PROVIDER_UNAVAILABLE.value
    assert session_count(db) == 0


def test_signing_in_again_refreshes_the_account_and_replaces_the_session_of_the_browser(client, db, identity_provider):
    finish_login(client)
    identity_provider.claims = make_claims(email="new@example.com", name="Ana Maria")
    finish_login(client)

    assert session_count(db) == 1
    assert db.scalar(select(func.count()).select_from(User)) == 1
    assert client.get("/auth/me").json()["email"] == "new@example.com"


def test_the_password_routes_of_the_old_sign_in_are_gone(client, user, session_factory):
    sign_in(client, session_factory, user)

    assert client.post("/auth/login", json={"email": "owner@example.com", "password": "x"}).status_code == 405
    assert client.post("/auth/register", json={}).status_code == 405
    assert client.put("/auth/me/password", json={}).status_code == 404
    assert client.patch("/auth/me", json={"name": "Ana"}).status_code == 405


# --- Sessions: refusal, sign-out, expiry and renewal (WCAG 2.2.1) ---

@pytest.mark.parametrize("cookie", [None, "forged-token"])
def test_requests_without_a_valid_session_are_refused(client, cookie):
    if cookie:
        client.cookies.set(SESSION_COOKIE_NAME, cookie)

    assert client.get("/auth/me").status_code == 401


def test_signing_out_ends_the_session_here_and_at_keycloak(client, db, identity_provider):
    finish_login(client)
    token = client.cookies.get(SESSION_COOKIE_NAME)

    assert client.post("/auth/logout").status_code == 204
    assert session_count(db) == 0
    assert identity_provider.ended_sessions == ["idp-session-1"]
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/auth/me").status_code == 401


def test_signing_out_without_a_session_still_succeeds(client, identity_provider):
    assert client.post("/auth/logout").status_code == 204
    assert identity_provider.ended_sessions == []


def test_signing_out_while_keycloak_is_down_still_ends_the_session_here(client, db, identity_provider):
    finish_login(client)
    identity_provider.unavailable = True

    assert client.post("/auth/logout").status_code == 204
    assert session_count(db) == 0


def test_signing_out_everywhere_ends_every_session_of_the_user(client, db, user, session_factory, identity_provider):
    sign_in(client, session_factory, user)
    laptop = sign_in(TestClient(app), session_factory, user)
    other = add_user(session_factory, subject="subject-2", email="other@example.com", name="Other")
    stranger = sign_in(TestClient(app), session_factory, other)

    assert client.post("/auth/logout-all").status_code == 204
    assert (client.get("/auth/me").status_code, laptop.get("/auth/me").status_code) == (401, 401)
    assert stranger.get("/auth/me").status_code == 200
    assert identity_provider.ended_accounts == ["subject-1"]


def test_an_expired_session_is_refused(client, db, user, session_factory):
    sign_in(client, session_factory, user)
    set_expiry(db, utc_now() - timedelta(seconds=1))

    assert client.get("/auth/me").status_code == 401


def test_a_session_in_use_is_renewed_after_half_its_lifetime(client, db, user, session_factory):
    token = sign_in(client, session_factory, user).cookies.get(SESSION_COOKIE_NAME)
    set_expiry(db, utc_now() + lifetime() * 0.4)

    response = client.get("/auth/me")

    assert SESSION_COOKIE_NAME in response.headers.get("set-cookie", "")
    assert stored_session(db, token).expires_at > utc_now() + lifetime() * 0.9


def test_a_fresh_session_is_not_renewed_on_every_request(client, user, session_factory):
    sign_in(client, session_factory, user)

    assert "set-cookie" not in client.get("/auth/me").headers


# --- Account page (GDPR Art. 16) ---

def test_the_account_page_is_the_keycloak_one(client):
    response = client.get("/auth/account")

    assert (response.status_code, response.headers["location"]) == (302, ACCOUNT_URL)


# --- Owner-only project access (MS3 §1.1.6) ---

def test_project_routes_need_a_signed_in_user(client):
    assert client.get("/projects").status_code == 401
    assert client.post("/projects", json=PROJECT_BODY).status_code == 401


def test_someone_elses_project_answers_like_a_missing_one(client, user, session_factory):
    project_id = sign_in(client, session_factory, user).post("/projects", json=PROJECT_BODY).json()["id"]
    other = add_user(session_factory, subject="subject-2", email="other@example.com", name="Other")
    stranger = sign_in(TestClient(app), session_factory, other)

    assert stranger.get("/projects").json() == []
    assert stranger.get(f"/projects/{project_id}").status_code == 404
    assert stranger.delete(f"/projects/{project_id}").status_code == 404
    assert client.get(f"/projects/{project_id}").status_code == 200
