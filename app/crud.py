from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models


def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.scalar(select(models.User).where(models.User.email == email))


def add_user(db: Session, email: str, hashed_password: str) -> models.User:
    user = models.User(email=email, hashed_password=hashed_password)
    db.add(user)
    return user


def add_note(db: Session, owner_id: int, title: str, content: str) -> models.Note:
    note = models.Note(title=title, content=content, owner_id=owner_id)
    db.add(note)
    return note


def list_notes(db: Session, owner_id: int, keyword: str | None = None) -> list[models.Note]:
    query = select(models.Note).where(models.Note.owner_id == owner_id).order_by(models.Note.id.desc())
    if keyword:
        like_keyword = f"%{keyword}%"
        query = query.where(
            models.Note.title.like(like_keyword) | models.Note.content.like(like_keyword),
        )
    return list(db.scalars(query))


def get_note(db: Session, note_id: int) -> models.Note | None:
    return db.get(models.Note, note_id)


def delete_note(db: Session, note: models.Note) -> None:
    db.delete(note)


def get_agent_session(db: Session, session_id: int) -> models.AgentSession | None:
    return db.get(models.AgentSession, session_id)


def get_owned_agent_message_for_update(
    db: Session,
    message_id: int,
    owner_id: int,
) -> models.AgentMessage | None:
    """锁定一条属于当前用户的消息，防止并发重复执行表单动作。"""
    query = (
        select(models.AgentMessage)
        .join(models.AgentSession)
        .where(
            models.AgentMessage.id == message_id,
            models.AgentSession.owner_id == owner_id,
        )
        .with_for_update()
    )
    return db.scalar(query)


def add_agent_session(db: Session, owner_id: int, title: str) -> models.AgentSession:
    session = models.AgentSession(owner_id=owner_id, title=title[:200] or "New chat")
    db.add(session)
    # flush 只把 SQL 发给数据库而不提交，用于在同一事务内取得自增 ID。
    db.flush()
    return session


def add_agent_message(
    db: Session,
    session_id: int,
    role: str,
    content: str,
    message_type: str = "text",
    message_data: dict | None = None,
) -> models.AgentMessage:
    message = models.AgentMessage(
        session_id=session_id,
        role=role,
        content=content,
        message_type=message_type,
        message_data=message_data,
    )
    db.add(message)
    return message


def list_agent_messages(db: Session, session_id: int) -> list[models.AgentMessage]:
    query = (
        select(models.AgentMessage)
        .where(models.AgentMessage.session_id == session_id)
        .order_by(models.AgentMessage.id.asc())
    )
    return list(db.scalars(query))
