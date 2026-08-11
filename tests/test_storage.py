import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException

from app.storage import OssStorage


class LocalStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(
            attachment_storage_backend="auto",
            local_upload_dir=self.temp_dir.name,
            local_upload_url_prefix="/api/uploads/local",
            oss_access_key_id="", oss_access_key_secret="", oss_endpoint="", oss_bucket="",
            oss_object_prefix="attachments", oss_signed_url_expire_seconds=3600,
            secret_key="test-secret-key-with-enough-entropy",
        )
        self.patch = patch("app.storage.get_settings", return_value=self.settings)
        self.patch.start()
        self.storage = OssStorage()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_upload_and_signed_read(self) -> None:
        uploaded = self.storage.upload(7, "notes.txt", "text/plain", b"hello")
        parsed = urlparse(uploaded.url)
        query = parse_qs(parsed.query)
        content, media_type = self.storage.read_local_signed(
            uploaded.object_key, int(query["expires"][0]), query["signature"][0],
        )
        self.assertEqual(content, b"hello")
        self.assertEqual(media_type, "text/plain")

    def test_invalid_signature_is_rejected(self) -> None:
        uploaded = self.storage.upload(7, "notes.txt", "text/plain", b"hello")
        with self.assertRaises(HTTPException) as context:
            self.storage.read_local_signed(uploaded.object_key, 4_000_000_000, "invalid")
        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
