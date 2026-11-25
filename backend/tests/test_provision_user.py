from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import USER_NAME_MAX_LENGTH, AgeGroup, LoginErrorCode, get_settings
from app.database.base import utc_now
from app.database.models import AuthSession, User
from app.services.auth.auth import (
    create_session,
    create_user,
    is_recently_authenticated,
    provision_user,
    revoke_session,
)
from app.services.auth.identity_provider import LoginRejectedError
from fake_identity_provider import make_claims


def test_the_first_sign_in_creates_the_account_from_keycloak(db):
    user = provision_user(db, make_claims(email="Ana@Example.com", name="Ana", is_admin=True))

    assert (user.subject, user.email, user.name, user.is_admin) == ("subject-1", "ana@example.com", "Ana", True)
    assert user.password_hash is None


def test_a_later_sign_in_refreshes_the_same_account(db):
    first = provision_user(db, make_claims())
    again = provision_user(
        db,
        make_claims(
            email="new@example.com",
            name="Ana Maria",
            age_group=AgeGroup.MINOR_WITH_GUARDIAN_CONSENT,
            is_admin=True,
        ),
    )

    assert again.id == first.id
    assert (again.email, again.name, again.age_group, again.is_admin) == (
        "new@example.com",
        "Ana Maria",
        AgeGroup.MINOR_WITH_GUARDIAN_CONSENT,
        True,
    )
    assert db.scalar(select(User).where(User.subject == "subject-1")).id == first.id


def test_a_name_longer_than_the_column_is_cut(db):
    user = provision_user(db, make_claims(name="A" * 60 + " " + "B" * 60))

    assert len(user.name) == USER_NAME_MAX_LENGTH


def test_an_email_of_an_account_from_before_keycloak_is_refused(db):
    create_user(db, "owner@example.com", "Owner", "correct horse battery staple")

    with pytest.raises(LoginRejectedError) as rejected:
        provision_user(db, make_claims(email="owner@example.com"))

    assert rejected.value.code == LoginErrorCode.LOGIN_FAILED
    assert db.scalar(select(User).where(User.subject == "subject-1")) is None


def test_a_session_keeps_its_keycloak_session_and_returns_it_when_revoked(db):
    user = provision_user(db, make_claims())
    signed_in_at = utc_now()
    new = create_session(db, user, idp_session_id="idp-session-1", authenticated_at=signed_in_at)

    assert (new.session.idp_session_id, new.session.authenticated_at) == ("idp-session-1", signed_in_at)
    assert revoke_session(db, new.token) == "idp-session-1"
    assert db.scalar(select(AuthSession)) is None


@pytest.mark.parametrize("token", [None, "unknown-token"])
def test_revoking_a_missing_session_returns_nothing(db, token):
    assert revoke_session(db, token) is None


@pytest.mark.parametrize("age, recent", [(timedelta(), True), (None, False)])
def test_a_recent_password_entry_allows_sensitive_actions(db, age, recent):
    user = provision_user(db, make_claims())
    authenticated_at = None if age is None else utc_now() - age
    session = create_session(db, user, authenticated_at=authenticated_at).session

    assert is_recently_authenticated(session) is recent


def test_an_old_password_entry_does_not(db):
    user = provision_user(db, make_claims())
    too_old = utc_now() - timedelta(seconds=get_settings().reauth_max_age_seconds + 1)
    session = create_session(db, user, authenticated_at=too_old).session

    assert is_recently_authenticated(session) is False