import hashlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.config import SESSION_COOKIE_NAME, SESSION_COOKIE_SAMESITE, AgeGroup, get_settings
from app.database.base import utc_now
from app.database.models import AuthSession, User
from app.main import app
from app.services.auth.auth import create_user
from app.services.storage.local import LocalStorage, get_storage
from app.services.storage.object_storage import get_object_storage
from conftest import TEST_PASSWORD, sign_in
from in_memory_object_storage import InMemoryObjectStorage

REGISTRATION = {"email": "Ana@Example.com", "name": "Ana", "password": TEST_PASSWORD, "age_group": "adult"}
LOGIN = {"email": "owner@example.com", "password": TEST_PASSWORD}
WRONG_LOGIN = {**LOGIN, "password": "not-the-password"}
NEW_PASSWORD = "a brand new passphrase"
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
def client(db_override, tmp_path):
    """A browser with no session yet."""
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path / "media")
    app.dependency_overrides[get_object_storage] = lambda: InMemoryObjectStorage()
    yield TestClient(app)
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


# --- Registration (MS3 §1.1.2, §1.4.1) ---

@pytest.mark.parametrize("age_group", list(AgeGroup))
def test_registering_signs_the_user_in(client, age_group):
    response = client.post("/auth/register", json={**REGISTRATION, "age_group": age_group.value})

    assert response.status_code == 201
    assert (response.json()["email"], response.json()["age_group"]) == ("ana@example.com", age_group.value)
    assert client.get("/auth/me").json()["name"] == "Ana"


def test_the_session_cookie_cannot_be_read_by_scripts_or_sent_cross_site(client):
    cookie = client.post("/auth/register", json=REGISTRATION).headers["set-cookie"].lower()

    assert "httponly" in cookie
    assert f"samesite={SESSION_COOKIE_SAMESITE}" in cookie


def test_an_email_can_only_be_registered_once_whatever_its_case(client):
    client.post("/auth/register", json=REGISTRATION)

    response = TestClient(app).post("/auth/register", json={**REGISTRATION, "email": "ana@EXAMPLE.COM"})

    assert response.status_code == 409


@pytest.mark.parametrize("field, value", [
    ("password", "short"),
    ("email", "not-an-email"),
    ("name", "   "),
    ("age_group", "under_13"),
    ("age_group", None),
])
def test_invalid_registrations_are_rejected(client, db, field, value):
    body = {**REGISTRATION, field: value} if value is not None else {k: v for k, v in REGISTRATION.items() if k != field}

    assert client.post("/auth/register", json=body).status_code == 422
    assert db.scalar(select(func.count()).select_from(User)) == 0


def test_passwords_and_tokens_are_only_stored_hashed(client, db):
    client.post("/auth/register", json=REGISTRATION)

    user = db.scalar(select(User))
    assert user.password_hash.startswith("$argon2id$")
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert stored_session(db, token).token_hash != token


# --- Sign-in and brute-force detection (MS3 §1.1.6) ---

def test_signing_in_with_the_right_password(client, user):
    response = client.post("/auth/login", json={**LOGIN, "email": "  Owner@Example.com "})

    assert response.status_code == 200
    assert client.get("/auth/me").json()["id"] == str(user.id)


def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(client, user):
    wrong = client.post("/auth/login", json=WRONG_LOGIN)
    unknown = client.post("/auth/login", json={**LOGIN, "email": "nobody@example.com"})

    assert (wrong.status_code, unknown.status_code) == (401, 401)
    assert wrong.json() == unknown.json()


def test_repeated_wrong_passwords_lock_the_account_for_a_while(client, db, user):
    for _ in range(get_settings().login_max_failed_attempts):
        wrong = client.post("/auth/login", json=WRONG_LOGIN)

    locked = client.post("/auth/login", json=LOGIN)
    assert locked.status_code == 401
    assert locked.json() == wrong.json()

    db.execute(update(User).values(locked_until=utc_now() - timedelta(seconds=1)))
    db.commit()
    assert client.post("/auth/login", json=LOGIN).status_code == 200


def test_a_successful_sign_in_resets_the_failure_count(client, user):
    for _ in range(2):
        for _ in range(get_settings().login_max_failed_attempts - 1):
            client.post("/auth/login", json=WRONG_LOGIN)
        assert client.post("/auth/login", json=LOGIN).status_code == 200


def test_a_disabled_account_cannot_sign_in_and_loses_its_sessions(client, db, user, session_factory):
    sign_in(client, session_factory, user)
    db.execute(update(User).values(is_active=False))
    db.commit()

    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/login", json=LOGIN).status_code == 401


def test_signing_in_again_replaces_the_previous_session_of_the_browser(client, db, user):
    client.post("/auth/login", json=LOGIN)
    client.post("/auth/login", json=LOGIN)

    assert session_count(db) == 1


# --- Sessions: refusal, sign-out, expiry and renewal (WCAG 2.2.1) ---

@pytest.mark.parametrize("cookie", [None, "forged-token"])
def test_requests_without_a_valid_session_are_refused(client, cookie):
    if cookie:
        client.cookies.set(SESSION_COOKIE_NAME, cookie)

    assert client.get("/auth/me").status_code == 401


def test_signing_out_ends_the_session_on_the_server(client, db, user):
    client.post("/auth/login", json=LOGIN)
    token = client.cookies.get(SESSION_COOKIE_NAME)

    assert client.post("/auth/logout").status_code == 204
    assert session_count(db) == 0
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get("/auth/me").status_code == 401


def test_signing_out_without_a_session_still_succeeds(client):
    assert client.post("/auth/logout").status_code == 204


def test_signing_out_everywhere_ends_every_session_of_the_user(client, db, user, session_factory):
    client.post("/auth/login", json=LOGIN)
    laptop = sign_in(TestClient(app), session_factory, user)
    other = create_user(db, "other@example.com", "Other", TEST_PASSWORD)
    stranger = sign_in(TestClient(app), session_factory, other)

    assert client.post("/auth/logout-all").status_code == 204
    assert (client.get("/auth/me").status_code, laptop.get("/auth/me").status_code) == (401, 401)
    assert stranger.get("/auth/me").status_code == 200


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


# --- Password change ---

def test_changing_the_password_signs_out_the_other_sessions(client, user, session_factory):
    client.post("/auth/login", json=LOGIN)
    laptop = sign_in(TestClient(app), session_factory, user)

    response = client.put("/auth/me/password", json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD})

    assert response.status_code == 204
    assert (client.get("/auth/me").status_code, laptop.get("/auth/me").status_code) == (200, 401)
    assert TestClient(app).post("/auth/login", json={**LOGIN, "password": NEW_PASSWORD}).status_code == 200
    assert TestClient(app).post("/auth/login", json=LOGIN).status_code == 401


def test_changing_the_password_needs_the_current_one_and_the_policy(client, user, session_factory):
    sign_in(client, session_factory, user)

    wrong = client.put("/auth/me/password", json={"current_password": "not-it", "new_password": NEW_PASSWORD})
    short = client.put("/auth/me/password", json={"current_password": TEST_PASSWORD, "new_password": "short"})

    assert (wrong.status_code, short.status_code) == (403, 422)
    assert TestClient(app).post("/auth/login", json=LOGIN).status_code == 200


# --- Owner-only project access (MS3 §1.1.6) ---

def test_project_routes_need_a_signed_in_user(client):
    assert client.get("/projects").status_code == 401
    assert client.post("/projects", json=PROJECT_BODY).status_code == 401


def test_someone_elses_project_answers_like_a_missing_one(client, db, user, session_factory):
    project_id = sign_in(client, session_factory, user).post("/projects", json=PROJECT_BODY).json()["id"]
    other = create_user(db, "other@example.com", "Other", TEST_PASSWORD)
    stranger = sign_in(TestClient(app), session_factory, other)

    assert stranger.get("/projects").json() == []
    assert stranger.get(f"/projects/{project_id}").status_code == 404
    assert stranger.delete(f"/projects/{project_id}").status_code == 404
    assert client.get(f"/projects/{project_id}").status_code == 200
