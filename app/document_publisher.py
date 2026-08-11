"""Transactional-outbox publisher from MySQL document jobs to RabbitMQ."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app import crud
from app.database import SessionLocal
from app.logging_config import configure_logging
from app.rabbitmq import connect, declare_topology, publish_document_job


logger = logging.getLogger(__name__)


def publish_batch(limit: int = 10) -> int:
    with SessionLocal() as db:
        jobs = crud.claim_unpublished_document_jobs(db, limit)
        if not jobs:
            db.rollback()
            return 0
        connection = connect()
        try:
            channel = connection.channel()
            declare_topology(channel)
            channel.confirm_delivery()
            for job in jobs:
                publish_document_job(channel, job.id)
                job.published_at = datetime.now(UTC).replace(tzinfo=None)
                logger.info("document_job_published", extra={"event": "document_job_published", "job_id": job.id, "owner_id": job.owner_id})
            db.commit()
            return len(jobs)
        finally:
            connection.close()


def run_forever() -> None:
    configure_logging()
    logger.info("document_publisher_started")
    while True:
        try:
            if not publish_batch():
                time.sleep(1)
        except Exception:
            logger.exception("document_publish_batch_failed")
            time.sleep(3)


if __name__ == "__main__":
    run_forever()
