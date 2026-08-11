import unittest
from io import BytesIO

from fastapi import HTTPException, UploadFile
from jose import jwt
from pydantic import ValidationError

from app.config import get_settings
from app.file_parser import MAX_FILE_SIZE, read_upload_limited
from app.schemas import AgentChatRequest, NoteCreate
from app.security import ALGORITHM, decode_access_token


class UploadLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_upload_before_unbounded_read(self) -> None:
        upload = UploadFile(filename="large.txt", file=BytesIO(b"x" * (MAX_FILE_SIZE + 1)))
        with self.assertRaises(HTTPException) as context:
            await read_upload_limited(upload)
        self.assertEqual(context.exception.status_code, 413)


class InputAndTokenTests(unittest.TestCase):
    def test_note_content_limit(self) -> None:
        with self.assertRaises(ValidationError):
            NoteCreate(title="title", content="x" * 50_001)

    def test_question_limit(self) -> None:
        with self.assertRaises(ValidationError):
            AgentChatRequest(question="x" * 10_001)

    def test_non_numeric_signed_subject_is_rejected(self) -> None:
        settings = get_settings()
        token = jwt.encode({"sub": "not-a-user"}, settings.secret_key, algorithm=ALGORITHM)
        self.assertIsNone(decode_access_token(token))
