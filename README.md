# Fieldnote AI Agent 后端

基于 FastAPI 的个人知识库 Agent 后端。项目不是单纯调用一次大模型的 Demo，而是把认证、用户数据隔离、笔记 CRUD、会话持久化、RAG 检索、SSE 流式输出、结构化业务表单、文件解析、视觉分析和阿里云 OSS 串成一条完整业务链路。

配套前端仓库位于同级目录 `../agent-frontfond`。

## 1. 项目能力

- 邮箱注册、bcrypt 密码哈希、JWT Bearer 鉴权。
- 按用户隔离的知识笔记增删改查与关键字搜索。
- Agent 会话和消息持久化，刷新页面可以恢复历史。
- 检索当前用户笔记后调用 Anthropic Messages 兼容模型。
- 没有命中笔记时使用模型自身知识回答，不伪造引用。
- 通过 SSE 增量返回模型文本、引用来源、附件和结构化表单。
- Markdown 回答、引用快照及表单完成状态持久化。
- TXT、Markdown、CSV、PDF、DOCX 和常见图片解析。
- 图片预处理、Tesseract OCR、可选视觉模型分析。
- 私有 OSS 对象上传、用户目录隔离、短期签名 URL 和孤儿文件删除。
- Pydantic 统一响应、全局异常处理和 Swagger API 文档。
- SQLAlchemy 2 ORM、Service 事务边界和 Alembic 数据库迁移。
- 未配置模型密钥时提供流式 Mock，方便本地调试完整链路。

## 2. 技术栈

| 分类 | 技术 | 项目中的作用 |
| --- | --- | --- |
| Web | FastAPI、Uvicorn | API、依赖注入、Swagger、SSE 响应 |
| 数据合同 | Pydantic v2 | 请求校验、响应裁剪、时间序列化 |
| 数据库 | SQLAlchemy 2、Alembic | ORM、Session、事务、结构迁移 |
| 认证 | Passlib、bcrypt、python-jose | 密码哈希、JWT 签发和校验 |
| Agent | LangGraph | 显式编排“检索 -> 生成”状态图 |
| 模型 | Anthropic Python SDK | 调用 Anthropic Messages 兼容接口 |
| 文件 | PyPDF、Pillow、pytesseract | PDF 提取、图片处理和 OCR |
| 存储 | oss2 | 阿里云 OSS 私有对象和签名 URL |
| 数据库默认值 | SQLite | 零依赖本地运行；可通过 URL 切换 MySQL |

## 3. 总体架构

```text
React Browser
  │  JSON / multipart / POST SSE
  ▼
Vite Proxy 或 Nginx
  ▼
FastAPI Route
  │  参数接收、Depends 鉴权、响应协议
  ▼
Service
  │  权限、事务、幂等、业务编排
  ├── CRUD ──> SQLAlchemy ──> SQLite / MySQL
  ├── Agent ──> LangGraph ──> Anthropic-compatible API
  ├── File Parser ──> PDF / DOCX / OCR / Image preprocess
  └── Storage ──> Aliyun OSS
```

依赖方向保持为：

```text
main(Route) -> services -> crud / agent / storage
                         -> schemas / models
```

核心原则：Route 不写业务，CRUD 不决定提交事务，Agent 不依赖 HTTP 和数据库，OSS SDK 不泄漏到业务代码。

## 4. 目录与模块职责

```text
app/
├── main.py          # FastAPI 入口、路由、依赖组装和 SSE Response
├── config.py        # .env 类型安全配置和单例缓存
├── database.py      # Engine、SessionLocal、Base、请求级 Session
├── models.py        # SQLAlchemy ORM 表和关系
├── schemas.py       # Pydantic 请求/响应 DTO
├── crud.py          # 纯数据访问，不 commit/rollback
├── services.py      # 权限、事务、幂等、会话和流式业务编排
├── agent.py         # RAG 状态、提示词、LangGraph 和模型适配
├── file_parser.py   # 文件校验、抽取、OCR、图片预处理
├── storage.py       # OSS 上传、签名、删除、归属校验
├── chat_forms.py    # 允许在聊天中执行的结构化动作白名单
├── security.py      # bcrypt 和 JWT
├── deps.py          # 当前用户鉴权依赖
└── responses.py     # 统一响应与全局异常处理
migrations/          # Alembic 迁移脚本
docs/                # 扩展面试资料
dev.sh               # 本地初始化、迁移和启动脚本
```

阅读代码推荐顺序：`main.py -> schemas.py -> services.py -> crud.py/models.py -> agent.py -> file_parser.py/storage.py`。

## 5. 快速启动

### 5.1 环境要求

- Python 3.11 或更高版本。
- 图片 OCR 需要系统安装 Tesseract；中文识别建议安装 `chi_sim` 语言包。
- 文件上传需要可用的阿里云 OSS Bucket。
- 真实问答需要兼容 Anthropic Messages API 的模型服务。

### 5.2 一键启动

```bash
cd python-agent-demo
chmod +x dev.sh
./dev.sh
```

脚本会创建虚拟环境、安装依赖、创建本地配置、执行迁移并启动开发服务器。

### 5.3 手动启动

```bash
cd python-agent-demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- 健康检查：`http://127.0.0.1:8000/health`
- Swagger：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

## 6. 环境变量

真实配置写入本地 `.env`，不要提交密钥。示例：

```dotenv
# 应用和鉴权
APP_NAME=Fieldnote AI Agent
APP_ENV=local
SECRET_KEY=请替换为随机长字符串
ACCESS_TOKEN_EXPIRE_MINUTES=120

# 默认可使用 SQLite；面试演示无需额外安装数据库
DATABASE_URL=sqlite:///./ai_agent_demo.db

# Anthropic Messages 兼容模型
ANTHROPIC_AUTH_TOKEN=你的模型密钥
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=你的文本模型
ANTHROPIC_VISION_MODEL=你的视觉模型
ANTHROPIC_VISION_ENABLED=true
API_TIMEOUT_MS=600000

# 阿里云 OSS
OSS_ACCESS_KEY_ID=你的AccessKeyId
OSS_ACCESS_KEY_SECRET=你的AccessKeySecret
OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com
OSS_BUCKET=你的Bucket名称
OSS_OBJECT_PREFIX=ai-agent-demo
OSS_SIGNED_URL_EXPIRE_SECONDS=3600
```

注意：

- `ANTHROPIC_VISION_MODEL` 为空时复用 `ANTHROPIC_MODEL`。
- 兼容服务若不接受 Anthropic `image` 内容块，应设置 `ANTHROPIC_VISION_ENABLED=false`。
- `VITE_` 前缀变量会进入浏览器构建产物，绝不能把模型或 OSS 长期密钥放到前端。
- 已经在聊天或截图中暴露过的 AccessKey/Token 应立即在云平台轮换。

### 6.1 可选 MySQL

应用使用 SQLAlchemy，替换连接 URL 即可切换 MySQL：

```dotenv
DATABASE_URL=mysql+pymysql://app_user:URL编码后的密码@127.0.0.1:3306/ai_agent_demo?charset=utf8mb4
```

切换后仍需执行：

```bash
alembic upgrade head
```

README 不把 MySQL 描述成默认已启用；当前实际数据库由本机 `.env` 的 `DATABASE_URL` 决定。

## 7. 数据模型

```text
User 1 ─── N Note
User 1 ─── N AgentSession
AgentSession 1 ─── N AgentMessage
```

| 表 | 关键字段 | 设计目的 |
| --- | --- | --- |
| `users` | `email`、`hashed_password` | 邮箱唯一；只保存密码哈希 |
| `notes` | `owner_id`、`title`、`content` | 用户知识库与数据隔离 |
| `agent_sessions` | `owner_id`、`title` | 保存连续对话容器 |
| `agent_messages` | `role`、`content`、`message_type`、`message_data` | 同时支持文本、表单、附件和引用快照 |

`message_data` 是 JSON 扩展字段：

- 普通回答保存 `used_notes` 快照。
- 用户附件消息保存文件元数据与 `object_key`。
- 表单消息保存 `kind/status/fields/result`。

引用使用“回答生成时快照”，而不是打开历史时重新查询当前 Note。这样笔记后来被修改或删除，旧回答仍能说明当时真正使用了什么上下文。

## 8. 认证与权限隔离

注册链路：

```text
UserCreate 校验 -> email 查重 -> bcrypt hash -> INSERT -> commit -> UserRead
```

登录链路：

```text
OAuth2 表单 -> bcrypt verify -> JWT(sub=user_id, exp=UTC time) -> Bearer Token
```

受保护接口通过 `Depends(get_current_user)`：

1. 读取 Authorization Bearer Token。
2. 校验 JWT 签名和过期时间。
3. 根据 `sub` 查询当前用户。
4. Service 再校验 Note、Session、Message 或 OSS 对象是否属于该用户。

这种双层校验避免“只要知道资源 ID 就能访问”的水平越权问题。

## 9. 普通聊天与 RAG

### 9.1 当前检索策略

当前实现使用数据库 `LIKE` 对标题和正文做关键字匹配，最多取 5 条真实命中笔记。它适合讲清楚 RAG 主链路，但不是语义向量检索。

```text
question
  -> owner_id 范围内检索 Notes
  -> 命中：把 Note DTO 拼成上下文
  -> 未命中：明确告诉模型没有笔记上下文
  -> 模型生成
  -> 保存完整答案和引用快照
```

未命中时不会拿“最近笔记”冒充引用，前端也不会显示虚假的“引用 1 条笔记”。

### 9.2 LangGraph

同步接口用两个节点表达 Agent：

```text
retrieve_notes -> generate_answer -> END
```

当前图很小，但显式状态图便于继续增加：向量召回、rerank、工具调用、人工审核、重试或条件分支。

## 10. SSE 流式协议

接口：`POST /agent/chat/stream`

选择 SSE 的原因：该场景主要是服务端单向增量推送，协议比 WebSocket 简单；使用 `fetch` 而不是原生 `EventSource`，因为请求需要 POST JSON 和 Authorization Header。

| 事件 | 数据 | 前端动作 |
| --- | --- | --- |
| `session` | `session_id` | 保存当前会话 |
| `sources` | `used_notes` | 展示真实引用 |
| `attachment` | 附件元数据 | 更新 OSS 预览和提取信息 |
| `delta` | 文本片段 | 追加 Markdown 内容 |
| `form` | 受控表单描述 | 渲染业务组件 |
| `done` | `message_id` | 用数据库 ID 替换临时 ID |
| `error` | `code/message` | 展示脱敏错误 |

模型调用可能耗时数秒，因此事务被拆成：

1. 短事务保存用户消息并提交。
2. 不持有数据库事务，流式调用模型。
3. 短事务保存完整助手消息和引用快照。

这能避免慢模型调用长期占用连接或持有数据库锁。

## 11. 文件与图片分析

### 11.1 前后端调用顺序

```text
选择文件
  -> POST /uploads 上传私有 OSS
  -> 返回 object_key + 临时签名 URL
  -> POST /agent/files/analyze
  -> 解析/OCR/图片预处理
  -> SSE 返回 attachment + delta + done
  -> 保存用户附件消息和助手分析
```

选中文件后立即上传，而不是等点击发送才上传。用户移除未发送附件时，前端调用 `DELETE /uploads` 清理孤儿对象。

### 11.2 文件限制

- 单文件最大 10 MB。
- 支持 `txt/md/csv/pdf/docx/png/jpg/jpeg/webp`。
- 文本尝试 UTF-8 BOM 和 GB18030。
- PDF 最多读取前 100 页；加密 PDF 明确拒绝。
- DOCX 直接解析 OpenXML 正文和表格文字。
- 图片限制像素数，EXIF 纠正方向，长边缩放到 1568，再压缩传给视觉模型。
- OCR 优先 `chi_sim+eng`，没有中文语言包时降级为英文。
- 抽取文本最多 60000 字符，避免请求体和模型费用失控。

OCR 和视觉模型职责不同：OCR 擅长读取文字，视觉模型负责主体、场景、构图和语义理解。项目将 OCR 结果作为视觉分析的补充上下文。

## 12. OSS 安全设计

对象键结构：

```text
{prefix}/{owner_id}/{yyyy}/{mm}/{dd}/{uuid}.{ext}
```

- AccessKey 只存在后端 `.env`。
- Bucket 可保持私有，浏览器使用短期签名 URL。
- 每次签名、删除、分析都会校验对象键的用户目录前缀。
- 数据库保存稳定的 `object_key`，不保存会过期的 URL。
- 读取历史时重新签名，因此刷新页面后图片仍可显示。

生产环境建议使用 RAM 子账号、最小 Bucket 权限、定期轮换密钥和对象生命周期规则。

## 13. 结构化表单消息

当问题命中“创建笔记”白名单意图时，服务端返回 `note_create` 表单描述。前端只对代码中明确支持的 `kind` 渲染组件，不执行模型生成的任意 URL。

表单提交时：

1. 查询当前用户拥有的消息并加行锁。
2. 检查消息类型和 `kind`。
3. 同一事务创建 Note 并将表单标记为 `completed`。
4. 重复提交返回第一次创建的 Note，保证幂等。

这是把 Agent 接入真实业务时的重要原则：模型可以建议动作，但服务端必须控制权限、参数和可执行范围。

## 14. API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录并签发 JWT |
| GET | `/users/me` | 当前用户 |
| POST | `/notes` | 创建笔记 |
| GET | `/notes` | 列表/关键字搜索 |
| GET | `/notes/{id}` | 笔记详情 |
| PUT | `/notes/{id}` | 更新笔记 |
| DELETE | `/notes/{id}` | 删除笔记 |
| POST | `/agent/chat` | 非流式问答 |
| POST | `/agent/chat/stream` | SSE 流式问答 |
| POST | `/uploads` | 上传 OSS |
| DELETE | `/uploads` | 清理未发送附件 |
| POST | `/agent/files/analyze` | SSE 文件分析 |
| POST | `/agent/forms/note` | 提交聊天内笔记表单 |
| GET | `/agent/sessions/{id}/messages` | 恢复会话历史 |

普通 JSON 响应统一为：

```json
{
  "data": {},
  "code": 200,
  "message": "success"
}
```

## 15. 数据库迁移

```bash
alembic current
alembic upgrade head
alembic revision --autogenerate -m "说明结构变更"
alembic downgrade -1
```

`create_all()` 适合一次性 Demo，但无法审查和追踪生产结构变化。Alembic 让每次 DDL 变更都有版本，可进入代码评审和发布流程。

## 16. 验证与调试

```bash
# Python 语法检查
.venv/bin/python -m compileall -q app

# 健康检查
curl http://127.0.0.1:8000/health

# 查看迁移版本
.venv/bin/alembic current
```

建议补充的自动化测试：

- 注册并发与 JWT 过期测试。
- Note/Session 水平越权测试。
- SSE 半包和 error 事件集成测试。
- 文件格式、超限、损坏、压缩炸弹测试。
- OSS 对象归属和签名 URL 测试。
- 表单重复提交幂等测试。

## 17. 面试讲法

### 30 秒版本

> 我做了一个 FastAPI + React 的个人知识库 Agent。后端用 JWT 做认证，SQLAlchemy 和 Alembic 管理用户、笔记、会话和消息；Agent 先检索当前用户真实命中的笔记，再通过 Anthropic 兼容模型回答，并用 SSE 流式返回。项目还支持 OSS 私有附件、PDF/DOCX/OCR/视觉分析和聊天内受控表单。架构上 Route、Service、CRUD、Agent 和 Storage 分层，Service 统一控制权限和事务。

### 2 分钟展开顺序

1. 先讲业务闭环：登录、写笔记、提问、引用、刷新恢复。
2. 再讲分层：Route 适配 HTTP，Service 管业务事务，CRUD 管 SQL，Agent 管模型。
3. 讲 SSE：为什么不用 EventSource、如何处理增量和错误。
4. 讲安全：JWT、owner_id、OSS 前缀、服务端表单白名单。
5. 讲工程取舍：短事务、引用快照、Mock 降级、Alembic。
6. 最后主动说明当前检索是 LIKE，生产化会升级为 embedding + vector DB + rerank。

### 高频追问

**为什么使用 SSE 而不是 WebSocket？** 该场景主要是服务端单向推送，SSE 更简单、可读；如果需要双向实时协作、语音或大量客户端事件，再考虑 WebSocket。

**为什么 CRUD 不 commit？** 一个业务动作可能包含多次数据库修改，只有 Service 知道完整原子边界。CRUD 自行提交会导致中途失败时无法整体回滚。

**为什么模型调用期间不持有事务？** 模型耗时不稳定，长事务会占连接、增加锁等待。先保存用户消息，调用结束后再短事务保存回答。

**RAG 是否真的使用向量数据库？** 当前版本是关键词检索，用于展示完整 RAG 数据流；生产化会引入分块、embedding、向量召回、metadata 过滤和 rerank。

**如何防止引用造假？** 只把真实检索结果传给模型，无命中就传明确的空上下文；前端引用来自服务端 `sources`，历史引用保存生成时快照。

**如何保护 OSS？** 长期 AccessKey 不进浏览器；对象按用户目录隔离，每次操作校验归属，只返回短期签名 URL。

## 18. 当前边界与生产化方向

当前已实现的是可运行的学习/面试项目，不应在面试中把下列方向说成已经完成：

- 将 LIKE 检索升级为 embedding、向量数据库、混合检索和 rerank。
- Redis 保存会话热点、限流和分布式幂等状态。
- 模型超时重试、熔断、多供应商降级和成本监控。
- 后台任务处理超大文件、扫描 PDF OCR 和病毒检测。
- 完整 pytest、容器化、CI/CD、日志链路和可观测性。
- OSS 使用 STS 临时凭证、回调校验和生命周期自动清理。

主动说明边界比把 Demo 包装成生产系统更可信。

## 19. 常见故障

- 401：检查 Bearer Token、JWT 过期时间和本机 `SECRET_KEY` 是否变化。
- 数据表缺失：执行 `alembic upgrade head`。
- 模型不可用：检查 token、base URL、模型名和 Anthropic 协议兼容性。
- 图片不能理解：确认视觉模型支持 `image` 内容块及 `ANTHROPIC_VISION_ENABLED=true`。
- OCR 中文失败：安装 Tesseract `chi_sim` 语言包。
- OSS 503：检查 Bucket、Endpoint、AccessKey 和 RAM 权限。
- 历史图片失效：数据库应保存 `object_key`，读取历史时由后端重新签名。
- SSE 被代理一次性返回：Nginx 关闭 proxy buffering，后端已设置 `X-Accel-Buffering: no`。

## 20. 配套前端

前端项目：`../agent-frontfond`

开发环境先启动本服务的 `8000` 端口，再启动前端的 `5173` 端口。前端通过 Vite 将 `/api` 代理到 FastAPI。
