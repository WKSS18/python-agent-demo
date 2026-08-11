import unittest
from unittest.mock import Mock, patch

from app.vector_store import CHUNK_OVERLAP, CHUNK_SIZE, VectorStore, _PREPARED_COLLECTIONS, split_note


class SplitNoteTests(unittest.TestCase):
    def setUp(self) -> None:
        _PREPARED_COLLECTIONS.clear()

    def test_short_note_keeps_title(self) -> None:
        self.assertEqual(split_note("Title", "Body"), ["Title\nBody"])

    def test_long_note_uses_overlapping_chunks(self) -> None:
        content = "x" * (CHUNK_SIZE + 100)
        chunks = split_note("Title", content)
        self.assertEqual(len(chunks), 2)
        first_body = chunks[0].split("\n", 1)[1]
        second_body = chunks[1].split("\n", 1)[1]
        self.assertEqual(first_body[-CHUNK_OVERLAP:], second_body[:CHUNK_OVERLAP])

    @patch("app.vector_store._embed", return_value=[[0.1, 0.2]])
    def test_index_payload_contains_tenant_boundary(self, _: Mock) -> None:
        store = VectorStore()
        store._request = Mock(side_effect=[{}, {}, {}, {}, {}, {}])
        self.assertEqual(store.index_note(7, 11, "Title", "Body"), 1)
        upsert = store._request.call_args_list[-1]
        point = upsert.kwargs["json"]["points"][0]
        self.assertEqual(point["payload"]["owner_id"], 7)
        self.assertEqual(point["payload"]["note_id"], 11)
        self.assertIn("-", point["id"])

    @patch("app.vector_store._embed", return_value=[[0.1, 0.2]])
    def test_search_always_filters_owner(self, _: Mock) -> None:
        store = VectorStore()
        store._request = Mock(return_value={"result": []})
        store.search(9, "question", 5)
        request = store._request.call_args
        must = request.kwargs["json"]["filter"]["must"]
        self.assertEqual(must, [{"key": "owner_id", "match": {"value": 9}}])


if __name__ == "__main__":
    unittest.main()
