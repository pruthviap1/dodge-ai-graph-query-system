from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        # Interpret relative paths from repo root to keep things predictable across platforms.
        path = PROJECT_ROOT / path
    return path.resolve()


def _load_env() -> None:
    # Prefer `backend/.env` (for Render), but also support repo-root `.env`.
    backend_env = BACKEND_ROOT / ".env"
    root_env = PROJECT_ROOT / ".env"
    if backend_env.exists():
        load_dotenv(backend_env)
    elif root_env.exists():
        load_dotenv(root_env)


_load_env()

DATA_DIR = _resolve_path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
LOGS_DIR = _resolve_path(os.getenv("LOGS_DIR", PROJECT_ROOT / "logs"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
if cors_origins_raw.strip() == "*":
    CORS_ORIGINS: list[str] = ["*"]
else:
    CORS_ORIGINS = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

