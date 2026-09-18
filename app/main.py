"""FastAPI 应用入口与 HTTP 路由。

本层负责协议适配：接收参数、注入 Session/当前用户、声明响应模型以及构造 SSE。
具体业务交给 Service，文件解析交给 file_parser，对象存储交给 storage，保持路由
函数短小且容易从 Swagger 理解。
"""

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import Response, StreamingResponse
import os

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_settings
from app.database import SessionLocal, check_dependencies, get_db
from app.deps import get_current_user
from app.file_parser import parse_uploaded_file, read_upload_limited
from app.responses import register_exception_handlers, success
from app.security import create_access_token
from app.services import AgentService, AuthService, DocumentImportService, KnowledgeService, NoteReviewService, NoteService
from app.middleware import RequestMiddleware
from app.logging_config import configure_logging
from app.storage import OssStorage
from app.security import decode_access_token
from app.voice_rooms import ROOMS, broadcast, create_room, get_room


configure_logging()
settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(RequestMiddleware, rate_limit_enabled=settings.rate_limit_enabled)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
register_exception_handlers(app)


# ------------------------------ 基础与认证 ------------------------------

@app.get("/health", response_model=schemas.ApiResponse[dict[str, str]])
def health_check() -> schemas.ApiResponse[dict[str, str]]:
    """存活探针：只证明应用进程仍能响应。"""
    return success({"status": "ok"})


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        payload = generate_latest(registry)
    else:
        payload = generate_latest()
    return Response(payload, media_type=CONTENT_TYPE_LATEST)


@app.get("/ready", response_model=schemas.ApiResponse[dict[str, str]])
def readiness_check() -> schemas.ApiResponse[dict[str, str]]:
    """就绪探针：数据库可连接时才允许流量进入。"""
    try:
        check_dependencies()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库暂不可用",
        ) from error
    return success({"status": "ready"})


@app.post("/auth/register", response_model=schemas.ApiResponse[schemas.UserRead])
def register(
    data: schemas.UserCreate,
    db: Session = Depends(get_db),
) -> schemas.ApiResponse[schemas.UserRead]:
    return success(AuthService(db).register(data))


@app.post("/auth/login", response_model=schemas.ApiResponse[schemas.Token])
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> schemas.ApiResponse[schemas.Token]:
    user = AuthService(db).authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return success(schemas.Token(access_token=create_access_token(str(user.id))))


@app.get("/users/me", response_model=schemas.ApiResponse[schemas.UserRead])
def get_me(
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.UserRead]:
    return success(current_user)


# ------------------------------ 知识笔记 ------------------------------


@app.post("/notes", response_model=schemas.ApiResponse[schemas.NoteRead])
def create_note(
    data: schemas.NoteCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.NoteRead]:
    return success(NoteService(db).create(owner_id=current_user.id, data=data))


@app.post(
    "/notes/agent-showcase",
    response_model=schemas.ApiResponse[schemas.AgentShowcaseImportResult],
)
def import_agent_showcase_notes(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.AgentShowcaseImportResult]:
    """把可检索、可引用的真实项目能力说明导入当前用户知识库。"""
    result = NoteService(db).import_agent_showcase(owner_id=current_user.id)
    message = "Agent 项目示例笔记已导入。" if result.created_count else "Agent 项目示例笔记已存在。"
    return success(result, message=message)


@app.post(
    "/notes/import",
    response_model=schemas.ApiResponse[schemas.DocumentImportTaskRead],
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_note_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.DocumentImportTaskRead]:
    """Persist a document and enqueue durable background parsing through RabbitMQ."""
    content = await read_upload_limited(file)
    uploaded = OssStorage().upload(
        owner_id=current_user.id, filename=file.filename,
        media_type=file.content_type, content=content,
    )
    note_title = (title or os.path.splitext(uploaded.name)[0]).strip()[:200] or "导入的文档"
    try:
        task = DocumentImportService(db).enqueue(
            current_user.id, uploaded.object_key, uploaded.name, uploaded.media_type, note_title,
        )
    except Exception:
        OssStorage().delete(current_user.id, uploaded.object_key)
        raise
    return success(task, message="文档已进入 RabbitMQ 后台处理队列。")


@app.get(
    "/notes/import/tasks/{task_id}",
    response_model=schemas.ApiResponse[schemas.DocumentImportTaskRead],
)
def get_document_import_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.DocumentImportTaskRead]:
    return success(DocumentImportService(db).get(current_user.id, task_id))


@app.get("/notes", response_model=schemas.ApiResponse[list[schemas.NoteRead]])
def list_notes(
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[list[schemas.NoteRead]]:
    return success(NoteService(db).list(owner_id=current_user.id, keyword=keyword))


@app.get("/notes/{note_id}", response_model=schemas.ApiResponse[schemas.NoteRead])
def get_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.NoteRead]:
    return success(NoteService(db).get(owner_id=current_user.id, note_id=note_id))


@app.put("/notes/{note_id}", response_model=schemas.ApiResponse[schemas.NoteRead])
def update_note(
    note_id: int,
    data: schemas.NoteUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.NoteRead]:
    return success(NoteService(db).update(owner_id=current_user.id, note_id=note_id, data=data))


@app.delete("/notes/{note_id}", response_model=schemas.ApiResponse[None])
def delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[None]:
    NoteService(db).delete(owner_id=current_user.id, note_id=note_id)
    return success(message="删除成功")


@app.post("/notes/{note_id}/review", response_model=schemas.ApiResponse[schemas.NoteReviewRead])
def review_note(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.NoteReviewRead]:
    """生成当天笔记复盘；重复请求返回同一份快照。"""
    return success(NoteReviewService(db).create_or_get(current_user.id, note_id))


@app.post("/notes/{note_id}/voice-room", response_model=schemas.ApiResponse[schemas.VoiceRoomRead])
def create_voice_room(
    note_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.VoiceRoomRead]:
    note = NoteService(db).get(current_user.id, note_id)
    room = create_room(current_user.id, note.id)
    return success(schemas.VoiceRoomRead(room_id=room.room_id, note_id=room.note_id, expires_at=room.expires_at))


@app.websocket("/voice-rooms/{room_id}/signal")
async def voice_room_signal(websocket: WebSocket, room_id: str, token: str = Query(default="")) -> None:
    user_id = decode_access_token(token)
    room = get_room(room_id)
    if not user_id or not room or len(room.peers) >= 2 or int(user_id) in room.peers:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    peer_id = int(user_id)
    with SessionLocal() as db:
        user = db.get(models.User, peer_id)
        display_name = (user.email.split("@", 1)[0] if user and user.email else f"用户{peer_id}")
    room.peers[peer_id] = websocket
    room.peer_names[peer_id] = display_name
    participants = [{"user_id": uid, "name": room.peer_names.get(uid, f"用户{uid}")} for uid in room.peers]
    ready = {"type": "room-ready", "peer_count": len(room.peers), "participants": participants}
    await websocket.send_json(ready)
    # 通知已经在房间内的另一端：第二位参与者已加入，可以开始 offer。
    await broadcast(room, peer_id, ready)
    try:
        while True:
            payload = await websocket.receive_json()
            if isinstance(payload, dict) and payload.get("type") in {"offer", "answer", "ice-candidate", "peer-ready", "hangup"}:
                await broadcast(room, peer_id, payload)
                if payload.get("type") == "hangup":
                    # “结束”属于房间级操作：任意一方结束后立即关闭双方连接并销毁房间。
                    ROOMS.pop(room_id, None)
                    for other_id, socket in list(room.peers.items()):
                        if other_id != peer_id:
                            await socket.close(code=1000, reason="room-ended")
                    await websocket.close(code=1000, reason="room-ended")
                    return
    except WebSocketDisconnect:
        pass
    finally:
        room.peers.pop(peer_id, None)
        room.peer_names.pop(peer_id, None)
        if not room.peers:
            ROOMS.pop(room_id, None)


@app.post(
    "/knowledge/reindex",
    response_model=schemas.ApiResponse[schemas.KnowledgeIndexTaskRead],
    status_code=status.HTTP_202_ACCEPTED,
)
def reindex_knowledge_base(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.KnowledgeIndexTaskRead]:
    """Enqueue an asynchronous rebuild of the current user's vectors."""
    return success(KnowledgeService(db).enqueue_reindex(owner_id=current_user.id))


@app.get(
    "/knowledge/tasks/{task_id}",
    response_model=schemas.ApiResponse[schemas.KnowledgeIndexTaskRead],
)
def get_knowledge_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.KnowledgeIndexTaskRead]:
    return success(KnowledgeService(db).get_task(current_user.id, task_id))


@app.post(
    "/knowledge/search/diagnostics",
    response_model=schemas.ApiResponse[schemas.KnowledgeSearchDiagnostics],
)
def diagnose_knowledge_search(
    data: schemas.KnowledgeSearchRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.KnowledgeSearchDiagnostics]:
    """调试混合召回、Rerank 和置信度门控；结果仍强制限定当前用户。"""
    return success(AgentService(db).diagnose_rag(current_user.id, data.query))


# ------------------------------ Agent 与 SSE ------------------------------


@app.post("/agent/chat", response_model=schemas.ApiResponse[schemas.AgentChatResponse])
def chat_with_agent(
    data: schemas.AgentChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.AgentChatResponse]:
    return success(AgentService(db).chat(owner_id=current_user.id, data=data))


@app.post("/agent/chat/stream")
def stream_chat_with_agent(
    data: schemas.AgentChatRequest,
    current_user: models.User = Depends(get_current_user),
) -> StreamingResponse:
    """以 SSE 返回 session、sources、delta、done/error 事件。"""
    return StreamingResponse(
        AgentService.stream_chat(owner_id=current_user.id, data=data),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/agent/files/analyze")
async def analyze_uploaded_file(
    file: UploadFile = File(...),
    prompt: str = Form(default="请总结并分析这份文件"),
    session_id: int | None = Form(default=None),
    object_key: str | None = Form(default=None),
    current_user: models.User = Depends(get_current_user),
) -> StreamingResponse:
    """先在服务端提取文本或执行 OCR，再通过 SSE 返回模型分析结果。"""
    content = await read_upload_limited(file)
    parsed_file = parse_uploaded_file(file.filename, file.content_type, content)
    return StreamingResponse(
        AgentService.stream_file_analysis(
            owner_id=current_user.id,
            parsed_file=parsed_file,
            prompt=prompt,
            session_id=session_id,
            object_key=object_key,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------ OSS 附件 ------------------------------


@app.post("/uploads", response_model=schemas.ApiResponse[schemas.UploadedFile])
async def upload_file(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.UploadedFile]:
    """由后端持有 OSS 凭证，上传私有对象并返回短期签名预览 URL。"""
    content = await read_upload_limited(file)
    uploaded = OssStorage().upload(
        owner_id=current_user.id,
        filename=file.filename,
        media_type=file.content_type,
        content=content,
    )
    return success(uploaded)


@app.delete("/uploads", response_model=schemas.ApiResponse[None])
def delete_uploaded_file(
    data: schemas.UploadedFileDelete,
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[None]:
    """移除附件时清理尚未发送的 OSS 对象。"""
    OssStorage().delete(owner_id=current_user.id, object_key=data.object_key)
    return success(message="附件已删除")


@app.get("/uploads/local/{object_key:path}", include_in_schema=False)
def read_local_attachment(
    object_key: str,
    expires: int = Query(...),
    signature: str = Query(...),
) -> Response:
    """Serve a private local attachment only through a short-lived signed URL."""
    content, media_type = OssStorage().read_local_signed(object_key, expires, signature)
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


# ------------------------------ 结构化表单与历史 ------------------------------


@app.get(
    "/agent/sessions",
    response_model=schemas.ApiResponse[list[schemas.AgentSessionRead]],
)
def list_agent_sessions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[list[schemas.AgentSessionRead]]:
    return success(AgentService(db).list_sessions(owner_id=current_user.id))


@app.post("/agent/forms/note", response_model=schemas.ApiResponse[schemas.NoteRead])
def submit_agent_note_form(
    data: schemas.AgentNoteFormSubmit,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[schemas.NoteRead]:
    """原子地创建 Note 并把对应表单消息标记为已完成。"""
    return success(AgentService(db).submit_note_form(owner_id=current_user.id, data=data))


@app.get(
    "/agent/sessions/{session_id}/messages",
    response_model=schemas.ApiResponse[list[schemas.AgentMessageRead]],
)
def list_agent_messages(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> schemas.ApiResponse[list[schemas.AgentMessageRead]]:
    return success(AgentService(db).list_messages(owner_id=current_user.id, session_id=session_id))
