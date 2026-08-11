"""Structured stdout logging shared by the API and background worker."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for key in (
            "event", "method", "path", "status", "duration_ms", "owner_id",
            "session_id", "note_id", "job_id", "operation", "attempts",
            "model", "ttft_ms", "input_tokens", "output_tokens", "hit_count",
            "top_score", "threshold", "chunk_count", "file_type", "file_size",
            "extracted_chars", "outcome",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("app", "app.requests", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.INFO)
