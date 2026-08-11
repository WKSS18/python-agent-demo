"""One-shot production smoke test for OSS -> RabbitMQ -> parser -> Qdrant."""

from __future__ import annotations

import time
from uuid import uuid4

from app import crud, models
from app.database import SessionLocal
from app.storage import OssStorage
from app.vector_store import VectorStore


def cleanup_previous_runs() -> None:
    with SessionLocal() as db:
        users = db.query(models.User).filter(models.User.email.like("rabbit-smoke-%@example.invalid")).all()
        for user in users:
            jobs = db.query(models.DocumentImportJob).filter_by(owner_id=user.id).all()
            for job in jobs:
                if job.note_id:
                    try:
                        VectorStore().delete_note(user.id, job.note_id)
                    except Exception:
                        pass
                try:
                    OssStorage().delete(user.id, job.object_key)
                except Exception:
                    pass
            db.query(models.DocumentImportJob).filter_by(owner_id=user.id).delete()
            db.query(models.KnowledgeIndexJob).filter_by(owner_id=user.id).delete()
            db.query(models.Note).filter_by(owner_id=user.id).delete()
            db.delete(user)
        db.commit()


def main() -> None:
    cleanup_previous_runs()
    marker = uuid4().hex
    storage = OssStorage()
    with SessionLocal() as db:
        user = models.User(email=f"rabbit-smoke-{marker}@example.invalid", hashed_password="disabled")
        db.add(user)
        db.commit()
        db.refresh(user)
        owner_id = user.id
    uploaded = storage.upload(owner_id, "rabbit-smoke.md", "text/markdown", b"# RabbitMQ smoke\nunique queue verification content")
    with SessionLocal() as db:
        job = crud.add_document_import_job(
            db, owner_id, uploaded.object_key, uploaded.name, uploaded.media_type, "RabbitMQ smoke"
        )
        db.commit()
        job_id = job.id

    note_id = None
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            with SessionLocal() as db:
                job = db.get(models.DocumentImportJob, job_id)
                note_id = job.note_id
                index_done = bool(
                    note_id
                    and db.query(models.KnowledgeIndexJob)
                    .filter_by(owner_id=owner_id, note_id=note_id, status="completed")
                    .first()
                )
                if job.status == "failed":
                    raise RuntimeError(job.last_error or "document job failed")
                if job.status == "completed" and index_done:
                    print(f"PASS job={job_id} note={note_id}: RabbitMQ import and Qdrant indexing completed")
                    return
            time.sleep(1)
        raise TimeoutError("document queue smoke test timed out")
    finally:
        if note_id:
            try:
                VectorStore().delete_note(owner_id, note_id)
            except Exception as exc:
                print(f"WARN vector cleanup failed: {exc}")
        with SessionLocal() as db:
            db.query(models.DocumentImportJob).filter_by(owner_id=owner_id).delete()
            db.query(models.KnowledgeIndexJob).filter_by(owner_id=owner_id).delete()
            db.query(models.Note).filter_by(owner_id=owner_id).delete()
            db.query(models.User).filter_by(id=owner_id).delete()
            db.commit()
        storage.delete(owner_id, uploaded.object_key)


if __name__ == "__main__":
    main()
