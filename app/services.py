"""业务服务层与事务边界。

Route 只负责 HTTP，CRUD 只负责 SQL；本模块负责权限、幂等、事务和跨模块编排。
流式模型调用使用独立 Session，并在模型调用前后拆分短事务，避免等待模型时长期
占用数据库连接或持有锁。
"""

import json
import logging
from collections.abc import Generator
from datetime import UTC, datetime
from threading import Thread

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import agent, chat_forms, crud, mcp_client, models, rag, schemas
from app.agent_showcase import SHOWCASE_NOTES, SHOWCASE_VERSION
from app.config import get_settings
from app.database import SessionLocal
from app.file_parser import ParsedFile
from app.security import hash_password, verify_password
from app.storage import OssStorage
from app.rag_pipeline import RagOutcome, RagPipeline
from app.vector_backends import create_vector_backend
from app.vector_store import VectorHit


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
    """注册与登录业务；数据库唯一索引兜底并发注册竞争。"""
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
    """知识笔记 CRUD，并统一校验 ``owner_id`` 防止水平越权。"""
    def create(self, owner_id: int, data: schemas.NoteCreate) -> models.Note:
        note = crud.add_note(
            self.db,
            owner_id=owner_id,
            title=data.title,
            content=data.content,
        )
        if get_settings().vector_store_enabled:
            self.db.flush()
            crud.add_index_job(self.db, "upsert", owner_id, note_id=note.id)
        self._commit()
        self.db.refresh(note)
        logger.info(
            "note_created",
            extra={"event": "note_created", "owner_id": owner_id, "note_id": note.id},
        )
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

        if get_settings().vector_store_enabled:
            crud.add_index_job(self.db, "upsert", owner_id, note_id=note.id)
        self._commit()
        self.db.refresh(note)
        logger.info(
            "note_updated",
            extra={"event": "note_updated", "owner_id": owner_id, "note_id": note.id},
        )
        return note

    def delete(self, owner_id: int, note_id: int) -> None:
        note = self.get(owner_id, note_id)
        if get_settings().vector_store_enabled:
            crud.add_index_job(self.db, "delete", owner_id, note_id=note_id)
        crud.delete_note(self.db, note)
        self._commit()
        logger.info(
            "note_deleted",
            extra={"event": "note_deleted", "owner_id": owner_id, "note_id": note_id},
        )

    def import_agent_showcase(self, owner_id: int) -> schemas.AgentShowcaseImportResult:
        """导入真实项目能力笔记；再次调用复用原笔记且不覆盖用户修改。"""
        source_keys = [item.source_key for item in SHOWCASE_NOTES]
        existing = crud.list_notes_by_source_keys(self.db, owner_id, source_keys)
        by_source_key = {note.source_key: note for note in existing}
        created: list[models.Note] = []
        selected: list[models.Note] = []
        for item in SHOWCASE_NOTES:
            note = by_source_key.get(item.source_key)
            if note is None:
                note = crud.add_note(
                    self.db,
                    owner_id=owner_id,
                    title=item.title,
                    content=item.content,
                    source_key=item.source_key,
                )
                self.db.flush()
                if get_settings().vector_store_enabled:
                    crud.add_index_job(self.db, "upsert", owner_id, note_id=note.id)
                created.append(note)
            selected.append(note)

        self._commit()
        for note in created:
            self.db.refresh(note)
        logger.info(
            "agent_showcase_imported",
            extra={
                "event": "agent_showcase_imported",
                "owner_id": owner_id,
                "version": SHOWCASE_VERSION,
                "created_count": len(created),
            },
        )
        return schemas.AgentShowcaseImportResult(
            version=SHOWCASE_VERSION,
            created_count=len(created),
            reused_count=len(selected) - len(created),
            notes=[schemas.NoteRead.model_validate(note) for note in selected],
            suggested_questions=[item.suggested_question for item in SHOWCASE_NOTES],
        )


class KnowledgeService(BaseService):
    """Vector index operations used for initial import and recovery."""

    def enqueue_reindex(self, owner_id: int) -> models.KnowledgeIndexJob:
        if not get_settings().vector_store_enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="向量知识库当前未启用。",
            )
        job = crud.add_index_job(self.db, "reindex", owner_id)
        self._commit()
        self.db.refresh(job)
        return job


class DocumentImportService(BaseService):
    """Create and expose durable document tasks consumed through RabbitMQ."""

    def enqueue(
        self, owner_id: int, object_key: str, filename: str, media_type: str, title: str,
    ) -> models.DocumentImportJob:
        job = crud.add_document_import_job(
            self.db, owner_id, object_key, filename, media_type, title,
        )
        self._commit()
        self.db.refresh(job)
        logger.info("document_job_queued", extra={"event": "document_job_queued", "job_id": job.id, "owner_id": owner_id})
        if not get_settings().is_production:
            # Local development does not require RabbitMQ. Run the exact same worker
            # function in a background thread; production keeps the durable queue path.
            from app.document_worker import process_job
            Thread(
                target=process_job,
                args=(job.id,),
                name=f"document-import-{job.id}",
                daemon=True,
            ).start()
        return job

    def get(self, owner_id: int, job_id: int) -> models.DocumentImportJob:
        job = crud.get_owned_document_import_job(self.db, job_id, owner_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档导入任务不存在。")
        return job

    def get_task(self, owner_id: int, task_id: int) -> models.KnowledgeIndexJob:
        job = crud.get_owned_index_job(self.db, task_id, owner_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="索引任务不存在。")
        return job


class AgentService(BaseService):
    """会话、消息、RAG、文件分析和结构化表单的应用服务。"""
    def chat(
        self,
        owner_id: int,
        data: schemas.AgentChatRequest,
    ) -> schemas.AgentChatResponse:
        """非流式兼容接口：保存提问、执行 Agent、保存完整回答。"""
        session_id = self._save_user_message(owner_id, data)
        memory = self._build_memory_snapshot(session_id, data.question)

        answer, used_notes = agent.run_agent(
            owner_id=owner_id,
            question=data.question,
            note_retriever=self._retrieve_note_snapshots,
            memory=memory,
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
        """恢复历史消息，并为每个私有 OSS 附件刷新签名 URL。"""
        self._get_owned_session(owner_id, session_id)
        storage = OssStorage()
        result: list[schemas.AgentMessageRead] = []
        for message in crud.list_agent_messages(self.db, session_id=session_id):
            item = schemas.AgentMessageRead.model_validate(message)
            item.attachment = storage.refresh_attachment_url(owner_id, item.attachment)
            result.append(item)
        return result

    def list_sessions(self, owner_id: int) -> list[models.AgentSession]:
        return crud.list_agent_sessions(self.db, owner_id)

    def submit_note_form(
        self,
        owner_id: int,
        data: schemas.AgentNoteFormSubmit,
    ) -> models.Note:
        """在同一事务中完成“创建笔记 + 标记表单完成”，并支持重复提交幂等。"""
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
        if get_settings().vector_store_enabled:
            crud.add_index_job(self.db, "upsert", owner_id, note_id=note.id)
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
            execution_trace: list[dict] = []

            def trace(step_id: str, title: str, description: str, step_status: str) -> str:
                step = {
                    "id": step_id,
                    "title": title,
                    "description": description,
                    "status": step_status,
                }
                for index, current in enumerate(execution_trace):
                    if current["id"] == step_id:
                        execution_trace[index] = step
                        break
                else:
                    execution_trace.append(step)
                return _sse_event("thinking", {"step": step})

            yield trace("intent", "理解问题", "正在识别用户意图与回答方式", "loading")
            form = chat_forms.match_form(data.question)
            if form:
                yield trace("intent", "理解问题", "识别为创建知识笔记请求", "success")
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

            yield trace("intent", "理解问题", "已识别为知识问答请求", "success")
            yield trace("memory", "整理会话上下文", "正在读取当前会话的相关历史消息", "loading")
            memory = service._build_memory_snapshot(session_id, data.question)
            yield trace(
                "memory",
                "整理会话上下文",
                "已准备会话上下文" if memory else "当前为独立问题，无需补充历史上下文",
                "success",
            )
            tool_context = ""
            direct_answer = ""
            selected_tool: tuple[str, dict] | None = None
            tool_intent = agent.is_mcp_intent(data.question)
            try:
                yield trace("mcp", "发现 MCP 工具", "正在从 Fieldnote MCP Server 获取工具清单", "loading")
                tools = mcp_client.list_tools()
                selected_tool = agent.select_mcp_tool(
                    data.question,
                    tools,
                    latitude=data.latitude,
                    longitude=data.longitude,
                )
                if selected_tool:
                    tool_name, arguments = selected_tool
                    yield trace("mcp", "调用 MCP 工具", f"正在调用 {tool_name}", "loading")
                    tool_context = mcp_client.call_tool(tool_name, arguments)
                    yield trace("mcp", "调用 MCP 工具", f"{tool_name} 已返回结果", "success")
                else:
                    yield trace("mcp", "发现 MCP 工具", f"已发现 {len(tools)} 个工具，本次问题无需调用", "success")
            except Exception:
                logger.exception("MCP tool execution failed for owner_id=%s", owner_id)
                yield trace("mcp", "MCP 工具调用", "工具服务暂时不可用，已降级为知识问答", "error")
            yield trace("retrieve", "检索知识笔记", "正在按当前用户范围执行语义检索与相关性过滤", "loading")
            if tool_intent and not selected_tool and not tool_context:
                direct_answer = agent.mcp_clarification(data.question)
            # A successful real-time tool call is the answer source. Do not attach
            # unrelated RAG candidates as citations when they were not used.
            used_notes = (
                []
                if tool_intent or (selected_tool is not None and bool(tool_context))
                else service._retrieve_note_snapshots(owner_id, data.question)
            )
            yield trace(
                "retrieve",
                "检索知识笔记",
                f"找到 {len(used_notes)} 条相关笔记" if used_notes else "未找到达到相关性阈值的笔记",
                "success",
            )
            # 查询会自动开启事务；模型生成可能持续数分钟，先结束只读事务，
            # 将连接归还连接池，生成完成后再使用当前 Session 开启短写事务。
            db.commit()
            yield _sse_event(
                "sources",
                {"used_notes": [note.model_dump(mode="json") for note in used_notes]},
            )

            yield trace("generate", "生成回答", "正在结合问题、会话上下文和检索结果组织回答", "loading")
            answer_parts: list[str] = []
            answer_stream = (
                iter((direct_answer,))
                if direct_answer
                else agent.stream_answer(data.question, used_notes, memory, tool_context)
            )
            for text_delta in answer_stream:
                answer_parts.append(text_delta)
                yield _sse_event("delta", {"content": text_delta})

            yield trace("generate", "生成回答", "回答生成完成", "success")

            message = crud.add_agent_message(
                db,
                session_id=session_id,
                role="assistant",
                content="".join(answer_parts),
                message_data=_note_message_data(used_notes, execution_trace),
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
        # 文件名和预览信息已在 attachment 中持久化，正文仅保存用户语句。
        request = schemas.AgentChatRequest(question=question, session_id=session_id)
        try:
            next_session_id = service._save_user_message(
                owner_id,
                request,
                message_data={"attachment": attachment},
            )
            yield _sse_event("session", {"session_id": next_session_id})
            yield _sse_event("attachment", {"attachment": attachment})

            # 消息已先持久化；即使当前模型无法分析图片，刷新后仍能恢复附件历史。
            if (
                parsed_file.image_content
                and not get_settings().anthropic_vision_enabled
                and not parsed_file.text
            ):
                fallback_answer = (
                    "图片已保存，但当前 DeepSeek 模型不支持图片输入，"
                    "且 OCR 未识别到可分析的文字。请配置支持视觉的模型后重试。"
                )
                message = crud.add_agent_message(
                    db,
                    session_id=next_session_id,
                    role="assistant",
                    content=fallback_answer,
                    message_data={"used_notes": [], "attachment": attachment},
                )
                service._commit()
                db.refresh(message)
                yield _sse_event("delta", {"content": fallback_answer})
                yield _sse_event("done", {"message_id": message.id})
                return

            answer_parts: list[str] = []
            for text_delta in agent.stream_file_analysis(
                parsed_file.name,
                parsed_file.text,
                question,
                parsed_file.extraction_method,
                parsed_file.image_content,
                parsed_file.image_media_type,
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
        """创建/校验会话并优先持久化用户消息，保证刷新后输入不会丢失。"""
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
        """执行混合召回、二阶段排序和置信度门控；低置信度时不返回引用。"""
        outcome = self._run_rag_pipeline(owner_id, question)
        snapshots = [] if not outcome.accepted else [
            schemas.NoteRead.model_validate(item.note).model_copy(update={"content": item.chunk})
            for item in outcome.evidence[:get_settings().rag_top_k]
        ]
        # 转成 DTO 后结束读事务，避免慢速模型调用长期占用数据库连接和事务。
        self.db.rollback()
        return snapshots

    def diagnose_rag(self, owner_id: int, query: str) -> schemas.KnowledgeSearchDiagnostics:
        """返回当前用户范围内的可解释检索分数，不暴露其他租户数据。"""
        outcome = self._run_rag_pipeline(owner_id, query)
        result = schemas.KnowledgeSearchDiagnostics(
            normalized_query=outcome.query,
            accepted=outcome.accepted,
            confidence=round(outcome.confidence, 6),
            reason=outcome.reason,
            confidence_components={
                key: round(value, 6) for key, value in outcome.confidence_components.items()
            },
            hits=[schemas.KnowledgeSearchHit(
                note_id=item.note.id, title=item.note.title, chunk=item.chunk,
                dense_score=round(item.dense_score, 6), sparse_score=round(item.sparse_score, 6),
                fusion_score=round(item.fusion_score, 6), rerank_score=round(item.rerank_score, 6),
                evidence_score=round(item.evidence_score, 6),
                source_trust=round(item.source_trust, 6),
                citable=any(evidence.note.id == item.note.id for evidence in outcome.evidence),
                retrieval_sources=list(item.retrieval_sources),
            ) for item in outcome.candidates],
        )
        self.db.rollback()
        return result

    def _run_rag_pipeline(self, owner_id: int, question: str) -> RagOutcome:
        all_notes = crud.list_notes(self.db, owner_id=owner_id)
        settings = get_settings()
        hits: list[VectorHit] = []
        if settings.vector_store_enabled:
            try:
                hits = create_vector_backend().search(owner_id, question, settings.rag_candidate_limit)
            except Exception:
                logger.exception("Vector search failed; falling back to local hybrid retrieval")
        if not hits:
            retrieved_notes = rag.retrieve_notes(question, all_notes, limit=settings.rag_top_k)
            hits = [
                VectorHit(note_id=item.note.id, chunk=item.matched_chunk, score=max(0.0, item.vector_score))
                for item in retrieved_notes
            ]
        return RagPipeline().run(owner_id, question, all_notes, hits)

    def _build_memory_snapshot(self, session_id: int, current_question: str) -> str:
        """取最近对话作为短期记忆，并避免把当前问题重复塞进 prompt。"""
        messages = crud.list_recent_agent_messages(self.db, session_id=session_id, limit=9)
        if messages and messages[-1].role == "user" and messages[-1].content == current_question:
            messages = messages[:-1]

        memory_lines: list[str] = []
        for message in messages[-8:]:
            role = "用户" if message.role == "user" else "助手"
            content = message.content.strip().replace("\n", " ")
            if content:
                memory_lines.append(f"{role}: {content[:500]}")
        return "\n".join(memory_lines)

    def _get_owned_session(self, owner_id: int, session_id: int) -> models.AgentSession:
        """集中执行会话归属检查，对不存在和无权访问统一返回 404。"""
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


def _note_message_data(used_notes: list[schemas.NoteRead], execution_trace: list[dict] | None = None) -> dict:
    """保存回答生成时的引用快照，避免历史记录依赖当前 Note 状态。"""
    data = {"used_notes": [note.model_dump(mode="json") for note in used_notes]}
    if execution_trace:
        data["execution_trace"] = execution_trace
    return data
