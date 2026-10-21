import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .db import get_db
from .models import User, Session

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "168"))  # 7 days


# ---------- Schemas ----------

class RegisterIn(BaseModel):
    email: EmailStr
    name: str
    password: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class SessionOut(BaseModel):
    session_token: str
    expires_at: datetime


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str


# ---------- Helpers ----------

def _create_session(db: DBSession, user: User) -> Session:
    token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    sess = Session(token=token, user_id=user.id, expires_at=expires)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[DBSession, Depends(get_db)],
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    stmt = select(Session).where(Session.token == creds.credentials)
    sess = db.execute(stmt).scalar_one_or_none()

    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")

    # Normalize timezone for comparison
    now = datetime.now(timezone.utc)
    expires = sess.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        db.delete(sess)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    return sess.user


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: RegisterIn, db: Annotated[DBSession, Depends(get_db)]):
    existing = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user = User(
        email=payload.email.lower(),
        name=payload.name,
        password_hash=pwd_ctx.hash(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, email=user.email, name=user.name)


@router.post("/login", response_model=SessionOut)
def login(payload: LoginIn, db: Annotated[DBSession, Depends(get_db)]):
    user = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()

    if user is None or not pwd_ctx.verify(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    sess = _create_session(db, user)
    return SessionOut(session_token=sess.token, expires_at=sess.expires_at)


@router.post("/logout", status_code=204)
def logout(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    db: Annotated[DBSession, Depends(get_db)],
):
    db.execute(delete(Session).where(Session.token == creds.credentials))
    db.commit()


@router.get("/me", response_model=UserOut)
def me(current_user: Annotated[User, Depends(get_current_user)]):
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
    )