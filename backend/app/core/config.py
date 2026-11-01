from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "openai/whisper-large-v3-turbo")
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "pt")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://pei:pei@postgres:5432/pei")

settings = Settings()
