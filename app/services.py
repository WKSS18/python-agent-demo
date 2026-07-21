import json
import logging
from collections.abc import Generator
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import agent, chat_forms, crud, models, schemas
from app.database import SessionLocal
from app.file_parser import ParsedFile
from app.security import hash_password, verify_password
from app.storage import OssStorage


logger = logging.getLogger(__name__)


class BaseService:
    """Service 统一控制写事务的提交和回滚。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _commit(self) -> None:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


class AuthService(BaseService):
    def register(self, data: schemas.UserCreate) -> models.User:
        if crud.get_user_by_email(self.db, data.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="邮箱已注册，请直接登录",
            )

        try:
            user = crud.add_user(
                self.db,
                email=data.email,
                hashed_password=hash_password(data.password),
            )
            self._commit()
        except IntegrityError as error:
            # 先查邮箱改善提示，唯一索引负责兜底并发注册竞争。
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="邮箱已注册，请直接登录",
            ) from error

        self.db.refresh(user)
        return user

    def authenticate(self, email: str, password: str) -> models.User | None:
        user = crud.get_user_by_email(self.db, email)
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user


class NoteService(BaseService):
    def create(self, owner_id: int, data: schemas.NoteCreate) -> models.Note:
        note = crud.add_note(
            self.db,
            owner_id=owner_id,
            title=data.title,
            content=data.content,
        )
        self._commit()
        self.db.refresh(note)
        return note

    def list(self, owner_id: int, keyword: str | None = None) -> list[models.Note]:
        return crud.list_notes(self.db, owner_id=owner_id, keyword=keyword)

    def get(self, owner_id: int, note_id: int) -> models.Note:
        note = crud.get_note(self.db, note_id)
        if not note or note.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="笔记不存在")
        return note

    def update(self, owner_id: int, note_id: int, data: schemas.NoteUpdate) -> models.Note:
        note = self.get(owner_id, note_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(note, key, value)

        self._commit()
        self.db.refresh(note)
        return note

    def delete(self, owner_id: int, note_id: int) -> None:
        note = self.get(owner_id, note_id)
        crud.delete_note(self.db, note)
        self._commit()


class AgentService(BaseService):
    def chat(
        self,
        owner_id: int,
        data: schemas.AgentChatRequest,
    ) -> schemas.AgentChatResponse:
        session_id = self._save_user_message(owner_id, data)

        answer, used_notes = agent.run_agent(
            owner_id=owner_id,
            question=data.question,
            note_retriever=self._retrieve_note_snapshots,
        )

        crud.add_agent_message(
            self.db,
            session_id=session_id,
            role="assistant",
            content=answer,
            message_data=_note_message_data(used_notes),
        )
        self._commit()

        return schemas.AgentChatResponse(
            session_id=session_id,
            answer=answer,
            used_notes=used_notes,
        )

    def list_messages(self, owner_id: int, session_id: int) -> list[schemas.AgentMessageRead]:
        self._get_owned_session(owner_id, session_id)
        storage = OssStorage()
        result: list[schemas.AgentMessageRead] = []
        for message in crud.list_agent_messages(self.db, session_id=session_id):
            item = schemas.AgentMessageRead.model_validate(message)
            item.attachment = storage.refresh_attachment_url(owner_id, item.attachment)
            result.append(item)
        return result

    def submit_note_form(
        self,
        owner_id: int,
        data: schemas.AgentNoteFormSubmit,
    ) -> models.Note:
        message = crud.get_owned_agent_message_for_update(
            self.db,
            message_id=data.message_id,
            owner_id=owner_id,
        )
        form_data = dict(message.message_data or {}) if message else {}
        if not message or message.message_type != "form" or form_data.get("kind") != "note_create":
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="表单不存在或无权操作",
            )

        # 重复提交返回第一次创建的 Note，实现接口幂等，不再新增第二条记录。
        if form_data.get("status") == "completed":
            result = form_data.get("result") or {}
            note_id = result.get("note_id")
            note = crud.get_note(self.db, note_id) if isinstance(note_id, int) else None
            if note and note.owner_id == owner_id:
                self._commit()
                self.db.refresh(note)
                return note
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该表单已经提交",
            )

        note = crud.add_note(
            self.db,
            owner_id=owner_id,
            title=data.title,
            content=data.content,
        )
        self.db.flush()
        message.message_data = {
            **form_data,
            "status": "completed",
            "result": {
                "note_id": note.id,
                "title": note.title,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        }
        self._commit()
        self.db.refresh(note)
        return note

    @classmethod
    def stream_chat(
        cls,
        owner_id: int,
        data: schemas.AgentChatRequest,
    ) -> Generator[str, None, None]:
        """使用独立 Session 覆盖完整流生命周期，并以多个短事务完成持久化。"""
        db = SessionLocal()
        service = cls(db)
        try:
            session_id = service._save_user_message(owner_id, data)
            yield _sse_event("session", {"session_id": session_id})

            form = chat_forms.match_form(data.question)
            if form:
                message = crud.add_agent_message(
                    db,
                    session_id=session_id,
                    role="assistant",
                    content="请填写下面的表单，我会把内容保存为知识笔记。",
                    message_type="form",
                    message_data=form,
                )
                service._commit()
                db.refresh(message)
                yield _sse_event("form", {"form": form})
                yield _sse_event("done", {"message_id": message.id})
                return

            used_notes = service._retrieve_note_snapshots(owner_id, data.question)
            yield _sse_event(
                "sources",
                {"used_notes": [note.model_dump(mode="json") for note in used_notes]},
            )

            answer_parts: list[str] = []
            for text_delta in agent.stream_answer(data.question, used_notes):
                answer_parts.append(text_delta)
                yield _sse_event("delta", {"content": text_delta})

            message = crud.add_agent_message(
                db,
                session_id=session_id,
                role="assistant",
                content="".join(answer_parts),
                message_data=_note_message_data(used_notes),
            )
            service._commit()
            db.refresh(message)
            yield _sse_event("done", {"message_id": message.id})
        except GeneratorExit:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Agent stream failed for owner_id=%s", owner_id)
            # 不把上游响应、密钥等内部细节暴露给浏览器。
            yield _sse_event(
                "error",
                {"code": status.HTTP_502_BAD_GATEWAY, "message": "模型服务暂时不可用，请稍后重试。"},
            )
        finally:
            db.close()

    @classmethod
    def stream_file_analysis(
        cls,
        owner_id: int,
        parsed_file: ParsedFile,
        prompt: str,
        session_id: int | None,
        object_key: str | None = None,
    ) -> Generator[str, None, None]:
        """保存附件消息，并把提取文本交给模型做 SSE 流式分析。"""
        db = SessionLocal()
        service = cls(db)
        attachment = parsed_file.attachment_data()
        if object_key:
            storage = OssStorage()
            storage.ensure_owned(owner_id, object_key)
            attachment.update(
                {
                    "object_key": object_key,
                    "url": storage.sign_get_url(owner_id, object_key),
                },
            )
        question = prompt.strip() or "请总结并分析这份文件"
        request = schemas.AgentChatRequest(
            question=f"上传文件：{parsed_file.name}\n分析要求：{question}",
            session_id=session_id,
        )
        try:
            next_session_id = service._save_user_message(
                owner_id,
                request,
                message_data={"attachment": attachment},
            )
            yield _sse_event("session", {"session_id": next_session_id})
            yield _sse_event("attachment", {"attachment": attachment})

            answer_parts: list[str] = []
            for text_delta in agent.stream_file_analysis(
                parsed_file.name,
                parsed_file.text,
                question,
                parsed_file.extraction_method,
            ):
                answer_parts.append(text_delta)
                yield _sse_event("delta", {"content": text_delta})

            message = crud.add_agent_message(
                db,
                session_id=next_session_id,
                role="assistant",
                content="".join(answer_parts),
                message_data={"used_notes": [], "attachment": attachment},
            )
            service._commit()
            db.refresh(message)
            yield _sse_event("done", {"message_id": message.id})
        except GeneratorExit:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("File analysis stream failed for owner_id=%s", owner_id)
            yield _sse_event(
                "error",
                {"code": status.HTTP_502_BAD_GATEWAY, "message": "文件已解析，但模型分析暂时失败，请稍后重试。"},
            )
        finally:
            db.close()

    def _save_user_message(
        self,
        owner_id: int,
        data: schemas.AgentChatRequest,
        message_data: dict | None = None,
    ) -> int:
        try:
            if data.session_id is None:
                session = crud.add_agent_session(self.db, owner_id, data.question)
            else:
                session = self._get_owned_session(owner_id, data.session_id)

            session_id = session.id
            crud.add_agent_message(
                self.db,
                session_id=session_id,
                role="user",
                content=data.question,
                message_data=message_data,
            )
            self._commit()
            return session_id
        except Exception:
            self.db.rollback()
            raise

    def _retrieve_note_snapshots(self, owner_id: int, question: str) -> list[schemas.NoteRead]:
        keyword_notes = crud.list_notes(self.db, owner_id=owner_id, keyword=question)
        fallback_notes = crud.list_notes(self.db, owner_id=owner_id)[:3]
        selected_notes = keyword_notes[:5] if keyword_notes else fallback_notes

        # 转成 DTO 后结束读事务，避免慢速模型调用长期占用数据库连接和事务。
        snapshots = [schemas.NoteRead.model_validate(note) for note in selected_notes]
        self.db.rollback()
        return snapshots

    def _get_owned_session(self, owner_id: int, session_id: int) -> models.AgentSession:
        session = crud.get_agent_session(self.db, session_id)
        if not session or session.owner_id != owner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在或无权访问",
            )
        return session


def _sse_event(event: str, data: dict) -> str:
    """统一编码 SSE，JSON 能安全承载换行、中文和 Markdown。"""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def _note_message_data(used_notes: list[schemas.NoteRead]) -> dict:
    """保存回答生成时的引用快照，避免历史记录依赖当前 Note 状态。"""
    return {"used_notes": [note.model_dump(mode="json") for note in used_notes]}
