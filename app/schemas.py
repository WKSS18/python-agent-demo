"""Pydantic DTO 与统一响应模型。

Schema 是 HTTP 边界的稳定合同：负责输入校验、输出裁剪和序列化；ORM Model 即使
新增内部字段，也不会未经审查自动返回给浏览器。
"""

from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """所有普通 JSON 接口统一使用的响应信封。"""

    data: T | None = None
    code: int = 200
    message: str = "success"


class UserCreate(BaseModel):
    """注册入参；bcrypt 对超长密码有限制，因此在接口层限制最大长度。"""
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
    """笔记部分更新 DTO；未传字段通过 ``exclude_unset`` 保持原值。"""
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


class UploadedFileDelete(BaseModel):
    object_key: str = Field(min_length=1)


class AgentMessageRead(BaseModel):
    """历史消息 DTO，同时暴露引用快照与附件元数据。"""
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

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        """SQLite 的 CURRENT_TIMESTAMP 是 UTC，但读取后不携带时区信息。"""
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.isoformat().replace("+00:00", "Z")
