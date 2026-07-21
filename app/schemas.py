from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """所有普通 JSON 接口统一使用的响应信封。"""

    data: T | None = None
    code: int = 200
    message: str = "success"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)


class UserRead(BaseModel):
    id: int
    email: EmailStr
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)


class NoteRead(BaseModel):
    id: int
    title: str
    content: str
    owner_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentChatRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: int | None = None


class AgentChatResponse(BaseModel):
    session_id: int
    answer: str
    used_notes: list[NoteRead]


class AgentNoteFormSubmit(NoteCreate):
    message_id: int = Field(gt=0)


class UploadedFile(BaseModel):
    name: str
    media_type: str
    size: int
    object_key: str
    url: str


class AgentMessageRead(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    message_type: str
    message_data: dict | None
    used_notes: list[NoteRead] = Field(default_factory=list)
    attachment: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
