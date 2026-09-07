"""Outbox worker that keeps Qdrant eventually consistent with MySQL."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from app import crud, models
from app.config import get_settings
from app.database import SessionLocal
from app.vector_backends import create_vector_backend


logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 6


def process_batch(limit: int = 10) -> int:
    settings = get_settings()
    if not settings.vector_store_enabled:
        return 0

    with SessionLocal() as db:
        crud.recover_stale_index_jobs(db)
        jobs = crud.claim_index_jobs(db, limit=limit)
        db.commit()

    for job in jobs:
        _process_job(job.id)
    return len(jobs)


def _process_job(job_id: int) -> None:
    started = time.perf_counter()
    with SessionLocal() as db:
        job = db.get(models.KnowledgeIndexJob, job_id)
        if not job or job.status != "processing":
            return
        operation, owner_id, note_id = job.operation, job.owner_id, job.note_id
        note_rows: list[tuple[int, int, str, str]] = []
        if operation == "upsert" and note_id is not None:
            note = db.get(models.Note, note_id)
            if note and note.owner_id == owner_id:
                note_rows = [(note.owner_id, note.id, note.title, note.content)]
        elif operation == "reindex":
            note_rows = [
                (note.owner_id, note.id, note.title, note.content)
                for note in crud.list_notes(db, owner_id=owner_id)
            ]

    logger.info(
        "knowledge_job_started",
        extra={
            "event": "knowledge_job_started", "job_id": job_id, "operation": operation,
            "owner_id": owner_id, "note_id": note_id, "attempts": job.attempts,
        },
    )

    error: Exception | None = None
    try:
        store = create_vector_backend()
        if operation == "upsert" and note_id is not None:
            if note_rows:
                store.index_note(*note_rows[0])
            else:
                store.delete_note(owner_id, note_id)
        elif operation == "delete" and note_id is not None:
            store.delete_note(owner_id, note_id)
        elif operation == "reindex":
            store.delete_owner(owner_id)
            for row in note_rows:
                store.index_note(*row)
        else:
            raise ValueError(f"unsupported index operation: {operation}")
    except Exception as exc:
        error = exc
        logger.exception("Knowledge index job %s failed", job_id)

    with SessionLocal() as db:
        job = db.get(models.KnowledgeIndexJob, job_id)
        if not job or job.status != "processing":
            return
        if error is None:
            job.status = "completed"
            job.last_error = None
            job.locked_at = None
        else:
            job.attempts += 1
            job.last_error = str(error)[:2000]
            job.locked_at = None
            if job.attempts >= MAX_ATTEMPTS:
                job.status = "failed"
            else:
                job.status = "pending"
                delay = min(300, 2 ** job.attempts)
                job.available_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=delay)
        db.commit()
    logger.info(
        "knowledge_job_finished",
        extra={
            "event": "knowledge_job_finished", "job_id": job_id, "operation": operation,
            "owner_id": owner_id, "note_id": note_id,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "outcome": "success" if error is None else "retry_or_failed",
        },
    )


def run_forever(poll_seconds: float = 2.0) -> None:
    from app.logging_config import configure_logging
    configure_logging()
    logger.info("Knowledge worker started")
    while True:
        processed = process_batch()
        if not processed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    run_forever()
