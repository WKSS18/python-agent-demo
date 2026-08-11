import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import crud, models
from app.database import Base
from app.document_worker import process_job
from app.file_parser import ParsedFile


class DocumentQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            user = models.User(email="document-queue@example.com", hashed_password="hash")
            db.add(user)
            db.commit()
            self.owner_id = user.id

    def tearDown(self) -> None:
        self.engine.dispose()

    def _session_factory(self):
        return Session(self.engine, expire_on_commit=False)

    def test_import_job_is_claimed_from_mysql_outbox(self) -> None:
        with Session(self.engine) as db:
            job = crud.add_document_import_job(
                db,
                owner_id=self.owner_id,
                object_key="documents/guide.md",
                filename="guide.md",
                media_type="text/markdown",
                title="Guide",
            )
            db.commit()
            job_id = job.id

        with Session(self.engine) as db:
            claimed = crud.claim_unpublished_document_jobs(db, limit=10)
            self.assertEqual([item.id for item in claimed], [job_id])

    def test_worker_creates_note_and_index_job_once(self) -> None:
        with Session(self.engine) as db:
            job = crud.add_document_import_job(
                db,
                owner_id=self.owner_id,
                object_key="documents/guide.md",
                filename="guide.md",
                media_type="text/markdown",
                title="Guide",
            )
            db.commit()
            job_id = job.id

        settings = SimpleNamespace(vector_store_enabled=True, document_max_attempts=3)
        with (
            patch("app.document_worker.SessionLocal", self._session_factory),
            patch("app.document_worker.get_settings", return_value=settings),
            patch("app.document_worker.OssStorage") as storage_type,
            patch(
                "app.document_worker.parse_uploaded_file",
                return_value=ParsedFile(
                    name="guide.md",
                    media_type="text/markdown",
                    size=7,
                    text="parsed content",
                    extraction_method="plain_text",
                    truncated=False,
                ),
            ),
        ):
            storage_type.return_value.download.return_value = b"# Guide"
            process_job(job_id)
            process_job(job_id)

        with Session(self.engine) as db:
            job = db.get(models.DocumentImportJob, job_id)
            self.assertEqual(job.status, "completed")
            self.assertEqual(job.stage, "completed")
            self.assertIsNotNone(job.note_id)
            self.assertEqual(db.query(models.Note).count(), 1)
            self.assertEqual(db.query(models.KnowledgeIndexJob).count(), 1)


if __name__ == "__main__":
    unittest.main()
