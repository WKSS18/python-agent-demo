"""RabbitMQ consumer for CPU-heavy document parsing and note creation."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from app import crud, models
from app.config import get_settings
from app.database import SessionLocal
from app.file_parser import parse_uploaded_file
from app.logging_config import configure_logging
from app.rabbitmq import connect, declare_topology
from app.storage import OssStorage


logger = logging.getLogger(__name__)


def process_job(job_id: int) -> bool:
    with SessionLocal() as db:
        job = db.get(models.DocumentImportJob, job_id)
        if not job or job.status == "completed":
            return True
        if job.status == "failed":
            return False
        job.status = "processing"
        job.stage = "parsing"
        db.commit()
        owner_id, object_key = job.owner_id, job.object_key
        filename, media_type, title = job.filename, job.media_type, job.title

    try:
        content = OssStorage().download(owner_id, object_key)
        parsed = parse_uploaded_file(filename, media_type, content)
        if not parsed.text.strip():
            raise ValueError("文档中没有提取到可用于知识检索的文字")
        with SessionLocal() as db:
            job = db.get(models.DocumentImportJob, job_id)
            if not job or job.status == "completed":
                return True
            job.stage = "creating_note"
            note = crud.add_note(db, owner_id, title, parsed.text[:50_000])
            db.flush()
            if get_settings().vector_store_enabled:
                crud.add_index_job(db, "upsert", owner_id, note.id)
            job.note_id = note.id
            job.status = "completed"
            job.stage = "completed"
            job.last_error = None
            db.commit()
        logger.info("document_job_completed", extra={"event": "document_job_completed", "job_id": job_id, "owner_id": owner_id, "note_id": note.id})
        return True
    except Exception as exc:
        logger.exception("document_job_failed", extra={"event": "document_job_failed", "job_id": job_id, "owner_id": owner_id})
        with SessionLocal() as db:
            job = db.get(models.DocumentImportJob, job_id)
            if not job:
                return False
            job.attempts += 1
            job.last_error = str(exc)[:2000]
            if job.attempts >= get_settings().document_max_attempts:
                job.status = "failed"
                job.stage = "failed"
            else:
                job.status = "queued"
                job.stage = "retrying"
                job.published_at = None
                job.available_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=2 ** job.attempts)
            db.commit()
        return False


def run_forever() -> None:
    configure_logging()
    connection = connect()
    channel = connection.channel()
    declare_topology(channel)
    channel.basic_qos(prefetch_count=1)

    def on_message(ch, method, properties, body):
        try:
            job_id = int(json.loads(body)["job_id"])
            completed = process_job(job_id)
            if completed:
                ch.basic_ack(method.delivery_tag)
            else:
                with SessionLocal() as db:
                    job = db.get(models.DocumentImportJob, job_id)
                    terminal = bool(job and job.status == "failed")
                if terminal:
                    ch.basic_reject(method.delivery_tag, requeue=False)
                else:
                    ch.basic_ack(method.delivery_tag)
        except Exception:
            logger.exception("document_message_invalid")
            ch.basic_reject(method.delivery_tag, requeue=False)

    channel.basic_consume(queue=get_settings().rabbitmq_document_queue, on_message_callback=on_message)
    logger.info("document_worker_started")
    channel.start_consuming()


if __name__ == "__main__":
    run_forever()
