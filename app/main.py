"""FastAPI 应用入口与 HTTP 路由。

本层负责协议适配：接收参数、注入 Session/当前用户、声明响应模型以及构造 SSE。
具体业务交给 Service，文件解析交给 file_parser，对象存储交给 storage，保持路由
函数短小且容易从 Swagger 理解。
"""

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.file_parser import parse_uploaded_file
from app.responses import register_exception_handlers, success
from app.security import create_access_token
from app.services import AgentService, AuthService, NoteService
from app.storage import OssStorage


settings = get_settings()
app = FastAPI(title=settings.app_name)
register_exception_handlers(app)


# ------------------------------ 基础与认证 ------------------------------

@app.get("/health", response_model=schemas.ApiResponse[dict[str, str]])
def health_check() -> schemas.ApiResponse[dict[str, str]]:
    return success({"status": "ok"})


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
    content = await file.read()
    await file.close()
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
    content = await file.read()
    await file.close()
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


# ------------------------------ 结构化表单与历史 ------------------------------


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
