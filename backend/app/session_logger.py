from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.config import LOGS_DIR


def log_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def new_session_id() -> str:
    return str(uuid.uuid4())


def log_ai_session(
    *,
    session_id: str,
    event: str,
    question: str,
    gemini_raw: str | None,
    answer: str,
    structured_query: dict[str, Any],
) -> str:
    """
    Appends a single jsonl row to `logs/ai_session_<YYYYMMDD>.jsonl`.
    """
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    log_path = LOGS_DIR / f"ai_session_{day}.jsonl"

    payload: dict[str, Any] = {
        "timestamp_utc": now.isoformat(),
        "session_id": session_id,
        "event": event,
        "question": question,
        "gemini_raw": gemini_raw,
        "structured_query": structured_query,
        "answer": answer,
    }
    log_jsonl(log_path, payload)
    return str(log_path)

