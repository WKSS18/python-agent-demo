"""纯数据访问层。

本模块只组织 SQLAlchemy 查询和对象增删，不调用 ``commit``/``rollback``。
事务边界由 Service 按完整业务动作统一控制，这样多个写操作可以保证原子性。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
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
    """按用户查询笔记；关键字同时匹配标题和正文。"""
    query = select(models.Note).where(models.Note.owner_id == owner_id).order_by(models.Note.id.desc())
    if keyword:
        like_keyword = f"%{keyword}%"
        query = query.where(
            models.Note.title.like(like_keyword) | models.Note.content.like(like_keyword),
        )
    return list(db.scalars(query))


def get_note(db: Session, note_id: int) -> models.Note | None:
    return db.get(models.Note, note_id)


def list_owned_notes_by_ids(db: Session, owner_id: int, note_ids: list[int]) -> list[models.Note]:
    if not note_ids:
        return []
    query = select(models.Note).where(models.Note.owner_id == owner_id, models.Note.id.in_(note_ids))
    notes = {note.id: note for note in db.scalars(query)}
    return [notes[note_id] for note_id in note_ids if note_id in notes]


def delete_note(db: Session, note: models.Note) -> None:
    db.delete(note)


def add_index_job(
    db: Session,
    operation: str,
    owner_id: int,
    note_id: int | None = None,
) -> models.KnowledgeIndexJob:
    job = models.KnowledgeIndexJob(operation=operation, owner_id=owner_id, note_id=note_id)
    db.add(job)
    db.flush()
    return job


def get_owned_index_job(db: Session, job_id: int, owner_id: int) -> models.KnowledgeIndexJob | None:
    return db.scalar(
        select(models.KnowledgeIndexJob).where(
            models.KnowledgeIndexJob.id == job_id,
            models.KnowledgeIndexJob.owner_id == owner_id,
        ),
    )


def recover_stale_index_jobs(db: Session, stale_minutes: int = 10) -> int:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=stale_minutes)
    result = db.execute(
        update(models.KnowledgeIndexJob)
        .where(
            models.KnowledgeIndexJob.status == "processing",
            models.KnowledgeIndexJob.locked_at < cutoff,
        )
        .values(status="pending", locked_at=None, last_error="worker lease expired"),
    )
    return result.rowcount or 0


def claim_index_jobs(db: Session, limit: int = 10) -> list[models.KnowledgeIndexJob]:
    now = datetime.now(UTC).replace(tzinfo=None)
    query = (
        select(models.KnowledgeIndexJob)
        .where(
            models.KnowledgeIndexJob.status == "pending",
            models.KnowledgeIndexJob.available_at <= now,
        )
        .order_by(models.KnowledgeIndexJob.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    jobs = list(db.scalars(query))
    for job in jobs:
        job.status = "processing"
        job.locked_at = now
    return jobs


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
    """创建会话并 flush 获取主键，但把是否提交留给调用方决定。"""
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
    """按主键升序恢复聊天顺序；会话归属必须由调用前的 Service 校验。"""
    query = (
        select(models.AgentMessage)
        .where(models.AgentMessage.session_id == session_id)
        .order_by(models.AgentMessage.id.asc())
    )
    return list(db.scalars(query))


def list_recent_agent_messages(
    db: Session,
    session_id: int,
    limit: int = 8,
) -> list[models.AgentMessage]:
    """取最近 N 条消息作为短期记忆，再恢复为自然对话顺序。"""
    query = (
        select(models.AgentMessage)
        .where(models.AgentMessage.session_id == session_id)
        .order_by(models.AgentMessage.id.desc())
        .limit(limit)
    )
    messages = list(db.scalars(query))
    return list(reversed(messages))
