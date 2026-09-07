import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import crud, models
from app.database import Base
from app.knowledge_worker import _process_job


class KnowledgeOutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_job_is_committed_with_business_transaction(self) -> None:
        with Session(self.engine) as db:
            user = models.User(email="outbox@example.com", hashed_password="hash")
            db.add(user)
            db.flush()
            note = crud.add_note(db, user.id, "title", "content")
            db.flush()
            job = crud.add_index_job(db, "upsert", user.id, note.id)
            db.commit()
            self.assertEqual(job.note_id, note.id)

        with Session(self.engine) as db:
            claimed = crud.claim_index_jobs(db, limit=10)
            self.assertEqual([item.id for item in claimed], [job.id])
            self.assertEqual(claimed[0].status, "processing")

    def test_rollback_removes_note_and_job(self) -> None:
        with Session(self.engine) as db:
            note = crud.add_note(db, 1, "title", "content")
            db.flush()
            crud.add_index_job(db, "upsert", 1, note.id)
            db.rollback()
        with Session(self.engine) as db:
            self.assertEqual(db.query(models.Note).count(), 0)
            self.assertEqual(db.query(models.KnowledgeIndexJob).count(), 0)

    def test_worker_completes_upsert_job(self) -> None:
        with Session(self.engine) as db:
            note = crud.add_note(db, 3, "title", "content")
            db.flush()
            job = crud.add_index_job(db, "upsert", 3, note.id)
            job.status = "processing"
            db.commit()
            job_id = job.id

        def session_factory():
            return Session(self.engine, expire_on_commit=False)

        with (
            patch("app.knowledge_worker.SessionLocal", session_factory),
            patch("app.knowledge_worker.create_vector_backend") as backend_factory,
        ):
            _process_job(job_id)
            backend_factory.return_value.index_note.assert_called_once()

        with Session(self.engine) as db:
            completed = db.get(models.KnowledgeIndexJob, job_id)
            self.assertEqual(completed.status, "completed")
