import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent_showcase import SHOWCASE_NOTES, SHOWCASE_VERSION
from app.database import Base
from app.services import NoteService


class AgentShowcaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    @patch("app.services.get_settings")
    def test_import_is_repeatable_and_preserves_user_edits(self, get_settings) -> None:
        get_settings.return_value.vector_store_enabled = False
        service = NoteService(self.db)

        first = service.import_agent_showcase(owner_id=7)
        self.assertEqual(first.version, SHOWCASE_VERSION)
        self.assertEqual(first.created_count, len(SHOWCASE_NOTES))
        self.assertEqual(first.reused_count, 0)

        stored = service.get(7, first.notes[0].id)
        stored.title = "我修改后的项目笔记"
        service._commit()

        second = service.import_agent_showcase(owner_id=7)
        self.assertEqual(second.created_count, 0)
        self.assertEqual(second.reused_count, len(SHOWCASE_NOTES))
        self.assertEqual(second.notes[0].title, "我修改后的项目笔记")

    def test_every_note_has_unique_source_key_and_question(self) -> None:
        source_keys = [item.source_key for item in SHOWCASE_NOTES]
        self.assertEqual(len(source_keys), len(set(source_keys)))
        self.assertTrue(all(item.suggested_question.endswith("？") for item in SHOWCASE_NOTES))


if __name__ == "__main__":
    unittest.main()
