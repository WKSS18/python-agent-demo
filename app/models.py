from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    notes: Mapped[list["Note"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    agent_sessions: Mapped[list["AgentSession"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    owner: Mapped["User"] = relationship(back_populates="notes")


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    owner: Mapped["User"] = relationship(back_populates="agent_sessions")
    messages: Mapped[list["AgentMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(20), default="text")
    message_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["AgentSession"] = relationship(back_populates="messages")

    @property
    def used_notes(self) -> list[dict]:
        """从文本消息的 JSON 快照中暴露引用，供历史响应 Schema 读取。"""
        if self.message_type != "text" or not isinstance(self.message_data, dict):
            return []
        notes = self.message_data.get("used_notes")
        return notes if isinstance(notes, list) else []

    @property
    def attachment(self) -> dict | None:
        """附件元数据保存在消息 JSON 中，历史消息可以直接恢复展示。"""
        if not isinstance(self.message_data, dict):
            return None
        attachment = self.message_data.get("attachment")
        return attachment if isinstance(attachment, dict) else None
