# backend/app/main.py
import os
from typing import Optional

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine
from . import models  # noqa: F401 — registers models with Base.metadata
from .auth import router as auth_router, get_current_user
from .models import User

app = FastAPI(title="PEI API")

BACKEND_AUTH_SECRET = os.getenv("BACKEND_AUTH_SECRET", "dev-secret-change-me")


async def verify_backend_auth(x_backend_auth: Optional[str] = Header(None)) -> bool:
    """Verify that the request comes from a trusted frontend."""
    if not x_backend_auth or x_backend_auth != BACKEND_AUTH_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid backend auth")
    return True


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth_router)


@app.get(
    "/api/user/profile",
    dependencies=[Depends(verify_backend_auth)],
)
def get_profile(current_user: User = Depends(get_current_user)):
    """
    Returns the logged-in user's profile.

    Requires BOTH headers:
      - X-Backend-Auth: <BACKEND_AUTH_SECRET>
      - Authorization: Bearer <session_token>
    """
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
    }