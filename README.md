# AI Agent Python 后端

这是一个用于学习和面试讲解的 FastAPI AI Agent 项目。后端提供 JWT 鉴权、Notes CRUD、MySQL 持久化、Alembic 迁移、LangGraph 编排和 SSE 流式聊天；同级目录 `../frontend` 是 React + TypeScript + Vite 前端。

## 已实现功能

- 注册、登录与 JWT Bearer 鉴权
- 按用户隔离的 Notes 增删改查
- 检索 Notes 后调用 Anthropic 兼容模型
- `session / sources / attachment / delta / form / done / error` SSE 事件
- 图片 OCR、PDF/Word/文本文件提取与大模型流式分析
- 结构化表单消息及历史恢复
- 会话与消息持久化到 MySQL
- CRUD 只访问数据，Service 统一事务
- Alembic 管理数据库版本

## 架构与目录

```text
React Browser
  │ POST /api/agent/chat/stream
  ▼
Vite Proxy / Nginx
  ▼
FastAPI Route       HTTP 输入输出、鉴权、SSE 响应
  ▼
Service             业务规则、权限校验、事务边界
  ├── CRUD -> SQLAlchemy -> MySQL
  └── Agent -> LangGraph -> Anthropic-compatible API
```

```text
app/
  main.py        路由入口和依赖注入
  config.py      .env 类型安全配置
  database.py    Engine、SessionLocal、数据库依赖
  models.py      SQLAlchemy 表模型
  schemas.py     Pydantic 请求与响应 DTO
  crud.py        无 commit 的数据访问函数
  services.py    业务规则、事务和 SSE 编排
  agent.py       Agent 流程、提示词、模型调用
  file_parser.py 文件安全校验、文档提取和图片 OCR
  storage.py     OSS 上传、对象权限校验和签名 URL
  chat_forms.py  受控表单意图和表单描述
  security.py    密码哈希和 JWT
  deps.py        当前登录用户依赖
migrations/      Alembic 迁移版本
docs/            项目说明和 Python 面试题
../frontend/     React 前端，与 Python 项目同级
```

依赖方向是 `Route -> Service -> CRUD/Agent`。CRUD 不知道事务何时完成，Agent 不知道数据库和 HTTP，方便单独测试和替换。

## 后端启动

推荐使用一键脚本：

```bash
cd /Users/admin/Desktop/面试/ai-agent-python-demo
./dev.sh
```

脚本会按需创建 `.venv`、安装发生变化的 Python 依赖、检查 Tesseract 中英文 OCR、首次创建 `.env`、执行 Alembic 迁移并启动 Uvicorn。macOS 已安装 Homebrew 时会自动补齐缺失的 Tesseract；已有 `.env` 不会被覆盖，日常启动通常只会执行迁移检查和启动服务。

下面是脚本所封装的手动步骤，主要用于理解或排查：

```bash
cd /Users/admin/Desktop/面试/ai-agent-python-demo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
test -f .env || cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Swagger：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 环境变量

真实密钥只放本机 `.env`，不要提交到仓库：

```dotenv
DATABASE_URL=mysql+pymysql://app_user:你的密码@127.0.0.1:3306/ai_agent_demo?charset=utf8mb4
ANTHROPIC_AUTH_TOKEN=你的模型密钥
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=你的模型名
API_TIMEOUT_MS=600000
OSS_ACCESS_KEY_ID=你的 AccessKey ID
OSS_ACCESS_KEY_SECRET=你的 AccessKey Secret
OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com
OSS_BUCKET=你的 Bucket 名称
OSS_OBJECT_PREFIX=ai-agent-demo
OSS_SIGNED_URL_EXPIRE_SECONDS=3600
```

兼容 Anthropic Messages API 的模型服务可以替换 base URL 和 model。不配置 token 时会走本地 mock，但仍使用相同 SSE 链路。

## MySQL 与 Alembic

首次创建数据库与应用账号：

```sql
CREATE DATABASE ai_agent_demo
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
CREATE USER 'app_user'@'localhost' IDENTIFIED BY '请换成强密码';
GRANT ALL PRIVILEGES ON ai_agent_demo.* TO 'app_user'@'localhost';
FLUSH PRIVILEGES;
```

Alembic 类似数据库结构的 Git。修改 Model 后生成迁移、审查迁移，再升级数据库：

```bash
alembic current
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
alembic downgrade -1
```

正式项目不要用 `create_all()` 偷偷修改生产库；迁移脚本应进入代码评审和发布流程。

## SSE 聊天流程

接口：`POST /agent/chat/stream`

1. JWT 解析当前用户。
2. 短事务创建或校验会话，并保存用户消息。
3. 若命中白名单表单意图，发送 `form` 事件并保存结构化消息。
4. 普通问答检索当前用户 Notes，转 DTO 后结束读事务。
5. 模型每生成一段文本，后端发送一个 `delta`。
6. 完成后用短事务保存完整助手消息和 `used_notes` 引用快照，再发送 `done`。

引用保存的是回答生成时的 Note 快照，而不是历史页面打开时重新检索。这样笔记后续被修改或删除，旧回答仍能准确说明当时引用了哪些内容。

| 事件 | 关键字段 | 前端行为 |
| --- | --- | --- |
| `session` | `session_id` | 保存会话 ID |
| `sources` | `used_notes` | 展示引用笔记 |
| `attachment` | `attachment` | 更新文件名、大小和提取方式 |
| `delta` | `content` | 追加模型文本 |
| `form` | `form` | 按消息类型渲染可操作表单 |
| `done` | `message_id` | 结束 pending 状态 |
| `error` | `message` | 展示脱敏错误 |

## OSS 上传与模型分析

文件处理分成两个职责清晰的接口：

1. `POST /uploads` 接收 `multipart/form-data` 的 `file`，校验类型和大小后上传到阿里云 OSS，返回 `object_key` 和短期签名 URL。
2. `POST /agent/files/analyze` 接收 `file`、`object_key`、可选的 `prompt` 和 `session_id`，解析文件并通过 SSE 返回模型分析结果。

前端先显示本地 Blob 预览，再调用 `/uploads`。上传成功后把 OSS `object_key` 交给分析接口；Service 会校验对象键是否属于当前用户，避免跨账号引用文件。数据库只保存对象键和附件元数据，不保存 AccessKey，也不依赖会过期的签名 URL。读取历史消息时，后端根据对象键重新生成签名 URL，所以私有 Bucket 中的图片刷新页面后仍能展示。

支持单个 10 MB 以内的 `txt/md/csv/pdf/docx/png/jpg/jpeg/webp`：

- 文本文件：后端按 UTF-8 或 GB18030 解码。
- PDF：使用 PyPDF 提取文本；加密文件和纯扫描件会给出明确错误。
- DOCX：提取正文段落和表格单元格。
- 图片：Tesseract 先做中英文 OCR，再把识别文本交给模型。

当前 DeepSeek Anthropic 兼容接口只支持文本消息，不支持直接发送 Anthropic `image/document` 内容块。因此本项目采用“文件解析/OCR -> 文本模型分析”的兼容方案。它适合截图文字、报告和合同内容总结，但不等于真正的视觉理解：图表趋势、照片物体和复杂版式可能分析不准。若以后换成支持视觉的模型，可以在 `file_parser.py` 之外新增视觉 Provider，而不必改路由、Service 和前端 SSE 协议。

附件元数据和 OSS 对象键保存在 `agent_messages.message_data`，原始文件保存在 OSS，不进入 MySQL。当前对象路径包含用户 ID、日期和随机 UUID，便于做账号隔离、生命周期清理和审计。

前端使用 `fetch + ReadableStream`，因为接口需要 POST JSON 和 Bearer Token，原生 `EventSource` 不适合。网络 chunk 不保证等于完整事件，因此前端必须缓存文本并按空行拆包。

## 表单消息场景

发送“帮我创建一条笔记”，`chat_forms.py` 会返回白名单内的 `note_create` 描述，SSE 发出 `form` 事件。前端渲染标题和内容字段，提交后调用 `POST /agent/forms/note`。

专用提交接口使用行锁，在同一个事务里创建 Note，并把 `message_data.status` 改为 `completed`、记录 `note_id`。同一表单重复提交会返回第一次创建的 Note，不会重复插入；刷新会话后前端只显示“笔记已创建”。表单接口与字段由服务端白名单决定，不直接执行大模型生成的任意 URL，避免越权调用和提示词注入。

## 事务设计

- `crud.py` 只做查询、`add`、`delete`、必要的 `flush`，不 `commit()`。
- Service 以业务动作为单位提交，异常统一回滚。
- 用户消息先提交，模型调用期间不持有数据库事务。
- 模型完成后再用短事务保存助手消息。

模型调用可能持续数秒。若把数据库事务包住整个调用，会长期占用连接并增加锁等待，所以这里拆成多个短事务。

## 常用接口

```text
POST   /auth/register
POST   /auth/login
GET    /users/me
POST   /notes
GET    /notes
GET    /notes/{id}
PUT    /notes/{id}
DELETE /notes/{id}
POST   /agent/chat
POST   /agent/chat/stream
POST   /uploads
POST   /agent/files/analyze
POST   /agent/forms/note
GET    /agent/sessions/{id}/messages
```

## 统一响应结构

除 SSE 流以外，所有 JSON 接口都返回统一信封：

```json
{
  "data": {},
  "code": 200,
  "message": "success"
}
```

- 成功：HTTP 状态和业务 `code` 都是 `200`，结果放在 `data`。
- 未登录或 token 失效：`code=401`，`data=null`。
- 参数错误：`code=422`，校验原因放在 `message`。
- 资源不存在、冲突和服务异常：分别使用 `404`、`409`、`500` 等业务码。
- SSE 成功响应继续使用事件协议；流内错误事件返回 `code` 和 `message`。

全局异常处理集中在 `app/responses.py`，路由通过泛型 `ApiResponse[T]` 声明真实 OpenAPI 响应结构。

`/auth/login` 使用 OAuth2 表单，`username` 字段实际填写邮箱。密码至少 6 位；账号未注册或密码错误会返回 401。

## 面试讲法

> 我做了一个 FastAPI 和 React 的知识问答项目。Agent 先按用户隔离检索 Notes，再通过 Anthropic 兼容协议调用模型。聊天用 SSE 流式返回，React 通过 fetch 读取 ReadableStream 并按事件类型渲染文本、引用来源或业务表单。数据层使用 SQLAlchemy 和 MySQL，Alembic 管理结构版本；CRUD 不提交事务，Service 统一控制 commit 和 rollback。模型调用前后使用短事务，避免慢请求长期占用数据库连接。

常见追问：

- 为什么 SSE：服务端单向持续推送文本，协议和断点处理比 WebSocket 简单。
- 为什么不用 EventSource：这里需要 POST body 和 Authorization 请求头。
- 如何处理半包：前端维护 buffer，按 `\n\n` 找事件边界，再解析 `data` JSON。
- 表单为何做白名单：不能信任模型生成的接口地址和参数，服务端必须控制可执行动作。
- 如何隔离数据：Note 与 Agent Session 都检查 `owner_id`。
- 如何保护密钥：仅从 `.env` 读取，示例文件只保留占位符。

详细项目问答见 [项目面试说明](docs/project-interview-guide.md)，Python 题库见 [30 道 Python 面试题](docs/python-interview-30.md)。

## 故障排查

- 401：先注册，确认邮箱和密码一致，密码至少 6 位。
- MySQL 失败：检查服务、端口、账号授权和 `DATABASE_URL`。
- 缺少字段或表：执行 `alembic upgrade head`。
- 模型失败：检查 token、base URL、模型名和协议兼容性。
- 前端 404：确认 FastAPI 在 8000 端口，Vite 代理目标正确。
- SSE 被一次性返回：Nginx 需关闭代理缓冲，后端已发送 `X-Accel-Buffering: no`。
