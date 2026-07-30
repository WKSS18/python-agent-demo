# AI Agent Python Demo 项目面试讲解

> 用途：面试前复习、项目介绍、深挖追问和现场演示。  
> 说明：文档严格区分“当前已实现”和“生产环境可改进”，面试时不要把改进项说成已完成的功能。

## 1. 项目一句话概括

这是一个 FastAPI + React 的 AI Agent 全栈项目，使用 SQLAlchemy 和 MySQL 持久化数据，bcrypt 和 JWT 完成认证，LangGraph 编排“短期记忆→混合 RAG 检索用户笔记→调用 LLM 生成回答”，并通过 SSE 流式返回文本或结构化表单消息。

## 2. 可直接复述的面试话术

### 2.1 30 秒版

> 我做了一个 FastAPI + React 的 AI Agent 项目。数据层用 SQLAlchemy 连接 MySQL，实现注册、JWT 鉴权、笔记 CRUD 和 Agent 问答。Agent 会从当前会话恢复短期记忆，再对用户 Notes 做关键词和向量相似度的混合 RAG 召回，最后通过 Anthropic Messages 兼容协议流式调用模型；聊天通过 SSE 增量返回，前端还能按消息类型渲染可操作表单。没有 API Key 时可以用 Mock 调试同一套流式链路。

### 2.2 2 分钟版

> 这个项目的目标是将常见 Python Web 能力和 AI Agent 链路放在一个可运行的小型项目中。  
> 在架构上，`main.py` 只负责路由、参数接收和响应；Pydantic Schema 负责输入输出校验；CRUD 层只做数据访问；Service 层集中业务规则和事务边界；SQLAlchemy Model 定义表和关系；`security.py` 负责密码哈希和 JWT；`deps.py` 通过 FastAPI 依赖注入统一获取当前用户。  
> 用户注册时，密码用 bcrypt 做单向哈希后再入库；登录成功后签发带过期时间的 JWT。Notes 和 Agent Session 都通过 `owner_id` 和当前用户绑定，查询和修改时会再校验归属，防止水平越权。  
> Agent 目前有两个节点：第一个节点从当前用户的 Notes 中检索上下文，第二个节点调用模型生成答案。Service 层会先把最近几轮消息整理成短期记忆，检索层用本地哈希向量模拟 embedding 并和关键词分数做混合排序。这个流程用 LangGraph 表达，后续可以在图中增加持久化向量库、rerank、工具调用、审核和重试节点。  
> 数据库已从开发时的 SQLite 切换到本地 MySQL 8.4，使用独立应用账号和 `utf8mb4`，并完成了注册写入、登录读取和数据库查询验证。

### 2.3 为什么做这个项目

> 我不想只写一个单次调用大模型的 Demo，而是想展示一个 AI 功能如何融入真实后端：它需要用户身份、业务数据、会话状态、权限隔离、数据持久化和外部服务降级。所以这个项目同时包含了常规 Web 后端和 Agent 编排。

## 3. 技术栈与选型理由

| 技术 | 在项目中的作用 | 选型理由 |
| --- | --- | --- |
| Python 3 | 主要开发语言 | AI 生态完整，适合快速构建 API 和 Agent |
| FastAPI | REST API 和 Swagger 文档 | 类型提示友好，自动 OpenAPI，支持依赖注入 |
| Pydantic v2 | 请求和响应校验 | 在边界处拦截无效数据，避免 ORM 对象直接暴露 |
| SQLAlchemy 2 | ORM 和 Session 管理 | 屏蔽大部分数据库方言差异，便于从 SQLite 切换 MySQL |
| MySQL 8.4 | 业务数据持久化 | 支持事务、索引、多连接，更接近正式后端环境 |
| PyMySQL | SQLAlchemy 的 MySQL DBAPI 驱动 | 纯 Python，本地安装简单 |
| Passlib + bcrypt | 密码哈希和验证 | bcrypt 自带 salt 且计算成本可调，适合密码存储 |
| python-jose | JWT 签发和解析 | 轻量，能完成 HS256 鉴权流程 |
| LangGraph | Agent 工作流编排 | 用显式状态和节点表达流程，方便扩展分支和循环 |
| Anthropic Python SDK | 模型流式调用 | `text_stream` 可直接迭代文本增量，并支持兼容服务 base URL |
| React + TypeScript + Vite | 聊天和 Notes 工作台 | 类型安全、开发代理配置简单、构建速度快 |

## 4. 项目分层和目录职责

```text
app/
├── main.py       # HTTP 路由、依赖组装和响应模型
├── config.py     # 从 .env 读取应用配置
├── database.py   # Engine、SessionLocal、Base 和 get_db
├── models.py     # SQLAlchemy ORM 模型和表关系
├── schemas.py    # Pydantic 请求/响应 DTO
├── security.py   # bcrypt 密码处理和 JWT
├── deps.py       # OAuth2 Bearer 和当前用户依赖
├── crud.py       # 数据访问，不 commit/rollback
├── services.py   # 业务规则和事务边界
└── agent.py      # 笔记检索、模型调用和 LangGraph 编排
```

分层的核心原则：

- 路由层处理 HTTP 语义，不直接拼 SQL。
- Schema 是 API 合同，Model 是持久化模型，两者不混用。
- CRUD 层只负责查询、`add`、`delete` 和必要的 `flush`，不决定事务提交。
- Service 层负责资源归属、业务规则和 `commit/rollback`，使一个业务用例共享明确的事务边界。
- 鉴权被封装成 FastAPI Dependency，受保护路由可复用。
- Agent 编排与 HTTP 解耦，可以被 API、定时任务或测试直接调用。

## 5. 总体请求链路

```text
Client / Swagger
      |
      v
FastAPI Route (main.py)
      |
      +--> Pydantic Schema 参数校验
      |
      +--> Depends(get_current_user) --> JWT 解析 --> 查询 User
      |
      +--> Service（业务 + 事务）
                 |
                 +--> CRUD --> SQLAlchemy Session --> PyMySQL --> MySQL
                 |
                 +--> LangGraph --> Mock 或 Anthropic-compatible Model
```

FastAPI 依赖注入的价值是：路由函数只声明“我需要数据库 Session”和“我需要当前用户”，具体的创建、验证和释放由依赖函数完成。

## 6. 数据库设计

### 6.1 表结构

#### users

| 字段 | 含义 | 约束/设计 |
| --- | --- | --- |
| id | 用户主键 | 整数主键、索引 |
| email | 登录邮箱 | 唯一索引，最长 255 |
| hashed_password | 密码哈希 | 只存 bcrypt 结果，不存明文 |
| created_at | 创建时间 | 数据库 `NOW()` 默认值 |

#### notes

| 字段 | 含义 | 约束/设计 |
| --- | --- | --- |
| id | 笔记主键 | 整数主键 |
| title | 标题 | 最长 200，建索引 |
| content | 正文 | Text |
| owner_id | 所属用户 | 外键指向 `users.id`，建索引 |
| created_at | 创建时间 | 数据库默认值 |
| updated_at | 更新时间 | ORM 更新时使用 `NOW()` |

#### agent_sessions

| 字段 | 含义 | 约束/设计 |
| --- | --- | --- |
| id | 会话主键 | 整数主键 |
| title | 会话标题 | 取首个问题的前 200 字符 |
| owner_id | 所属用户 | 外键与索引 |
| created_at | 创建时间 | 数据库默认值 |

#### agent_messages

| 字段 | 含义 | 约束/设计 |
| --- | --- | --- |
| id | 消息主键 | 整数主键 |
| session_id | 所属会话 | 外键与索引 |
| role | 消息角色 | `user` 或 `assistant` |
| content | 消息内容 | Text |
| message_type | 消息类型 | `text` 或 `form` |
| message_data | 结构化数据 | JSON，普通文本为空 |
| created_at | 创建时间 | 数据库默认值 |

### 6.2 表关系

```text
User 1 ---- N Note
User 1 ---- N AgentSession
AgentSession 1 ---- N AgentMessage
```

ORM 关系上配置了 `cascade="all, delete-orphan"`，代表从 ORM 删除父对象时，关联的子对象会一起被处理。面试时要注意：这是 ORM 层级的 cascade，当前外键未显式配置数据库级 `ON DELETE CASCADE`。

### 6.3 为什么需要索引

- `users.email` 用于注册查重和登录，适合唯一索引。
- `notes.owner_id` 用于按用户查询笔记。
- `agent_sessions.owner_id` 用于用户会话隔离。
- `agent_messages.session_id` 用于按会话查询消息。

生产化后可以根据实际 SQL 增加联合索引，例如 `notes(owner_id, id)` 和 `agent_messages(session_id, id)`，对应“按用户/会话过滤后按 id 排序”的查询。是否增加要根据 `EXPLAIN` 和数据量判断，不是索引越多越好。

## 7. MySQL 接入过程

### 7.1 当前状态

- 本机已安装 MySQL 8.4 LTS。
- MySQL 通过 Homebrew Service 后台运行。
- 数据库名为 `ai_agent_demo`，字符集为 `utf8mb4`。
- 本地开发 `.env` 已配置 `mysql+pymysql://ai_agent_app:***@127.0.0.1:3306/ai_agent_demo?charset=utf8mb4`。
- 应用使用独立数据库账号 `ai_agent_app`，不直接使用 root。
- root 账号只用于本地数据库管理，不写入项目配置，也不应该在面试或演示中展示密码。
- `.env` 中的 `DATABASE_URL` 已从 SQLite URL 改为 MySQL URL。
- 已执行 `alembic upgrade head`，MySQL 中存在 `users`、`notes`、`agent_sessions`、`agent_messages` 和 `alembic_version` 表。
- 已通过 `app.database.check_database_connection()` 验证应用账号能连接 MySQL。

### 7.2 连接字符串

```dotenv
DATABASE_URL=mysql+pymysql://<user>:<url-encoded-password>@127.0.0.1:3306/ai_agent_demo?charset=utf8mb4
```

含义：

- `mysql+pymysql`：SQLAlchemy 使用 MySQL 方言和 PyMySQL 驱动。
- `127.0.0.1:3306`：通过 TCP 连接本地 MySQL。
- `charset=utf8mb4`：支持完整 Unicode，包括四字节字符。
- 密码中的 `!`、`@`、`:` 等特殊字符应做 URL 编码。

本地验证常用命令：

```bash
brew services list
mysql -h 127.0.0.1 -u ai_agent_app -p ai_agent_demo
alembic upgrade head
```

面试时不要展示 `.env`、root 密码、OSS 密钥或模型 API Key。可以只说“项目使用独立应用账号连接 MySQL，root 仅用于本地管理”。

### 7.3 从 SQLite 切换到 MySQL 为什么代码改动很小

`database.py` 通过 SQLAlchemy `create_engine(settings.database_url)` 创建引擎，业务代码使用 ORM 查询，没有大量依赖 SQLite 的原生 SQL。因此切换的核心是：

1. 安装 MySQL Server 和 PyMySQL 驱动。
2. 创建数据库和最小权限的应用账号。
3. 替换 `DATABASE_URL`。
4. 重启应用，让配置和 Engine 重新加载。
5. 执行建表和读写验证。

SQLite 需要 `check_same_thread=False`，而 MySQL 不需要，所以项目只在 URL 以 `sqlite` 开头时增加该参数。

本项目在 `database.py` 中还针对非 SQLite 连接启用了连接池配置：

- `pool_pre_ping=True`：借出连接前先检查连接是否仍然有效。
- `pool_recycle`：定期回收连接，减少 MySQL 空闲连接超时带来的错误。
- `pool_size`、`max_overflow`、`pool_timeout`：控制连接池容量和等待时间。

### 7.4 Alembic 数据库迁移

当前项目已使用 Alembic 取代 FastAPI 启动时的 `Base.metadata.create_all()`。首次启动或发布新版本前执行：

```bash
alembic upgrade head
```

当前本地 MySQL 已执行到最新迁移，表结构由 `migrations/versions/` 中的版本脚本创建和维护。

修改 ORM Model 后，使用 `alembic revision --autogenerate` 对比当前数据库和 `Base.metadata`，生成候选迁移文件。自动生成结果必须人工审查，再执行 upgrade。Alembic 的价值是：

- 每次结构变更都有版本。
- 可以审查实际 DDL。
- 可以按顺序升级，必要时回滚。
- 多个环境的数据库结构更容易保持一致。

## 8. 注册、登录和 JWT 鉴权

### 8.1 注册链路

```text
POST /auth/register
  -> UserCreate 校验 email 和密码长度
  -> 按 email 查重
  -> bcrypt hash(password)
  -> INSERT users
  -> commit + refresh
  -> UserRead 输出，不包含 hashed_password
```

关键点：

- bcrypt 是单向哈希，不是可逆加密。
- 每次哈希都包含随机 salt，相同密码的哈希通常不同。
- API 响应使用 `UserRead`，不将哈希值暴露给客户端。
- Pydantic 将密码限制在 6–72 字符；72 与 bcrypt 的输入限制有关。更严谨的实现应按 UTF-8 字节长度校验。

### 8.2 登录链路

```text
POST /auth/login (OAuth2 form)
  -> 按 email 查 User
  -> bcrypt verify(明文, 哈希)
  -> 生成 JWT: sub=user.id, exp=过期时间
  -> 返回 access_token + bearer
```

### 8.3 访问受保护接口

```text
Authorization: Bearer <token>
  -> OAuth2PasswordBearer 取出 token
  -> HS256 验签并校验 exp
  -> 读取 sub
  -> 按 sub 查询 User
  -> 注入 current_user
```

### 8.4 JWT 的优缺点

优点：

- 服务端不必为每个 access token 保存 Session。
- 可在多实例间使用相同签名配置验证。
- `sub`、`exp` 等声明能携带必要信息。

缺点：

- 签发后不易立即撤销。
- 如果 token 被窃取，在过期前可能被滥用。
- 不应把敏感数据直接放在 payload；JWT 默认是签名，不是加密。

生产化改进：短效 access token + refresh token、token 轮换、撤销表/黑名单、密钥轮换、HTTPS、登录限流。

## 9. Notes CRUD 和数据隔离

### 9.1 CRUD 实现

- Create：创建 Note 时强制写入 `current_user.id`。
- Read List：查询条件始终包含 `owner_id == current_user.id`。
- Read One：按主键获取后再比较 `owner_id`。
- Update：只更新 Pydantic 输入中实际传入的字段。
- Delete：Service 先校验资源归属，再调用 CRUD 删除并统一提交。

### 9.2 为什么资源不属于当前用户时返回 404

如果返回 403，攻击者可以推断这个 ID 的资源确实存在，只是自己没权限。统一返回 404 能降低资源枚举风险。

### 9.3 部分更新

```python
update_data = data.model_dump(exclude_unset=True)
for key, value in update_data.items():
    setattr(note, key, value)
```

`exclude_unset=True` 的意义是只处理客户端真正传入的字段，避免未传字段被默认值覆盖。当前路由使用 PUT，但行为更接近 PATCH；生产项目可以改成 PATCH 使 HTTP 语义更准确。

## 10. Agent 工作流

### 10.1 当前流程

```text
用户问题
   |
   v
获取/创建 AgentSession
   |
   v
保存 user message
   |  提交第一个短事务
   |
   v
构造短期记忆
   |  从当前 session 最近消息中排除本次问题
   |
   v
retrieve_notes
   |  当前用户 Notes -> 切块 -> 本地哈希向量 -> 关键词 + 向量混合排序
   |  无真实命中则不返回引用，让模型用自身知识回答
   v
generate_answer
   |  system prompt + 会话记忆 + notes 上下文 + 当前问题
   |  有 API Key: Anthropic SDK messages.stream().text_stream
   |  无 API Key: 本地 Mock
   |  每个文本增量发送 SSE delta
   v
保存 assistant message
   |  提交第二个短事务
   |
   v
发送 done；JSON 兼容接口仍返回 answer + used_notes + session_id
```

若问题命中“创建笔记”白名单意图，会跳过模型调用，直接发送结构化 `form` 事件。表单的 `kind` 和字段由服务端控制，前端按类型映射组件并调用受鉴权的 Notes API。

面试时可以强调一个工程取舍：外部模型调用可能持续数秒甚至数分钟，所以项目先提交用户消息，再结束 Notes 查询产生的只读事务，等模型生成结束后才开启短写事务保存 assistant message。这样不会在等待模型时长期占用 MySQL 连接和事务锁。

### 10.2 AgentState 的作用

`AgentState` 是节点之间传递的显式状态：

```python
class AgentState(TypedDict):
    question: str
    owner_id: int
    memory: str
    context: str
    used_notes: list[schemas.NoteRead]
    answer: str
```

相比用多个全局变量，显式 State 有几个优点：

- 节点输入输出更清晰。
- 方便增加分支、循环和检查点。
- 便于测试某个节点的纯逻辑。
- 便于记录每个阶段的中间结果。

当前 LangGraph 图仍保持两节点：

1. `retrieve_notes`：调用注入的检索函数，不直接依赖 SQLAlchemy，降低 Agent 层和数据库层耦合。
2. `generate_answer`：把 `question`、`memory`、`used_notes` 组织成 prompt，然后流式调用模型。

后续如果要扩展，可以在图中增加：

- `rewrite_query`：根据历史对话改写用户问题。
- `retrieve_vector`：从向量库召回候选 chunks。
- `rerank`：用 reranker 对候选上下文重新排序。
- `tool_call`：需要查天气、查订单、查数据库时调用工具。
- `guardrail`：输出前做安全、引用完整性或格式检查。
- `summarize_memory`：长会话超过窗口后压缩历史记忆。

### 10.3 LLM 调用怎么实现

项目把模型调用集中放在 `app/agent.py` 的 `_stream_model()`：

```python
client = Anthropic(
    api_key=settings.anthropic_auth_token,
    base_url=settings.anthropic_base_url,
    timeout=settings.api_timeout_ms / 1000,
)
with client.messages.stream(
    model=model or settings.anthropic_model,
    max_tokens=2_048,
    system=system_prompt,
    messages=[{"role": "user", "content": user_content}],
) as stream:
    yield from stream.text_stream
```

关键点：

- 协议：使用 Anthropic Messages API。`system` 单独传系统提示词，用户输入放到 `messages`。
- 供应商切换：`base_url` 从配置读取，兼容 Anthropic 协议的网关或模型服务可以替换。
- 流式输出：`messages.stream()` 返回增量文本，后端通过 Python generator 一段段 `yield`，路由层再包装成 SSE。
- 超时：`api_timeout_ms` 集中配置，避免模型长时间无响应拖死请求。
- Mock 降级：没有 `ANTHROPIC_AUTH_TOKEN` 时仍按分块流式返回本地 Mock，前端不用维护两套逻辑。
- 多模态：文件分析接口在开启视觉模型时把图片 base64 放到 content 列表里，文本和图片走同一个 `_stream_model()`。

面试追问“为什么不在 route 里直接调 LLM”时，可以这样答：

> Route 只处理 HTTP 协议，LLM 客户端、prompt 组织和 mock 降级放在 Agent 层。这样普通 JSON 接口、SSE 接口、文件分析和测试都能复用同一套模型适配逻辑。

### 10.4 记忆怎么实现

项目里有两类记忆：

| 类型 | 当前实现 | 作用 |
| --- | --- | --- |
| 短期记忆 | `agent_messages` 中最近几轮会话，由 `AgentService._build_memory_snapshot()` 拼成 prompt | 让模型理解上下文，例如“继续解释刚才那个方案” |
| 长期记忆/知识记忆 | 用户主动创建的 `notes`，通过 RAG 召回 | 让模型回答和用户个人知识库相关的问题 |

短期记忆不是存在 Python 全局变量里，而是来自数据库消息表：

```text
agent_sessions 1 ---- N agent_messages
```

调用 `/agent/chat/stream` 时，服务层先保存当前用户问题，然后读取最近 9 条消息，排除刚刚保存的本次问题，最多保留最近 8 条历史消息：

```python
messages = crud.list_recent_agent_messages(self.db, session_id=session_id, limit=9)
if messages and messages[-1].role == "user" and messages[-1].content == current_question:
    messages = messages[:-1]
```

这样做的好处：

- 刷新页面后历史上下文仍然存在。
- 多个会话之间通过 `session_id` 隔离。
- 不依赖单进程内存，后端重启后仍可恢复。
- 可以控制最近 N 条，避免把完整历史塞进 prompt 导致 token 爆炸。

当前短期记忆是“滑动窗口”。生产环境可以升级为：

1. 滑动窗口 + 摘要记忆：最近消息原文保留，较早消息压缩成 summary。
2. 用户画像记忆：把稳定偏好单独抽取，例如语言、技术栈、项目背景。
3. 可删除记忆：给用户提供查看、修改和删除长期记忆的能力。
4. 记忆权限隔离：所有记忆必须带 `owner_id/session_id`，不能跨用户串数据。

### 10.5 当前检索是不是 RAG

它是一个轻量 RAG 链路，因为它确实先检索当前用户数据，再将上下文提供给生成模型。现在已经不只是 SQL `LIKE`，而是在 `app/rag.py` 中实现了请求内临时向量索引：

```text
用户问题
  -> tokenize
  -> 本地哈希向量 embed

当前用户 Notes
  -> title + content
  -> chunk
  -> 本地哈希向量 embed
  -> cosine similarity
  -> keyword overlap
  -> hybrid score
  -> topK notes
```

这里的“向量”不是调用商业 embedding API，而是用 hashing trick 生成固定维度向量，目的是在不增加外部服务的情况下，把 RAG 的核心流程体现在代码里：

- `_chunk_note()`：把长 Note 切成有 overlap 的 chunk。
- `_embed()`：把 token hash 到 256 维向量，并做归一化。
- `_cosine_similarity()`：计算 query 向量和 chunk 向量的余弦相似度。
- `_keyword_overlap()`：补充精确关键词匹配，避免纯向量召回漂移。
- `retrieve_notes()`：按混合分数排序，同一 Note 只保留最高分 chunk。

当前混合分数：

```text
score = keyword_score * 0.55 + vector_score * 0.45
```

这个权重不是固定真理，只是 Demo 里的保守选择：关键词更可解释，向量召回能处理近义表达。真实项目会通过离线评测集调权重、阈值和 topK。

当前实现有一个重要原则：没有真实命中的 Notes 时，不用“最近笔记”冒充引用，而是明确给模型传入空上下文，让模型基于自身知识回答。这样历史消息里的引用来源更可信。

完整 RAG 可以扩展为：

1. 文档切分和清洗。
2. 调用 embedding 模型，例如 `text-embedding-3-large` 或供应商等价模型。
3. 将 chunk、embedding、metadata 写入向量库。
4. Query 改写，处理“它/这个/刚才”的指代。
5. 向量召回 + 关键词召回的混合检索。
6. Rerank。
7. 上下文去重、截断和 Token 预算。
8. 模型生成并返回引用。
9. 质量评估和反馈闭环。

### 10.6 生产向量库会怎么设计

如果从当前 Demo 升级为真正向量 RAG，可以新增一张 chunk 表或接入向量库：

| 字段 | 说明 |
| --- | --- |
| id | chunk 主键 |
| owner_id | 用户隔离字段 |
| note_id | 来源 Note |
| chunk_index | Note 内顺序 |
| content | chunk 文本 |
| embedding | 向量，维度由 embedding 模型决定 |
| content_hash | 判断内容是否变化，避免重复 embedding |
| created_at / updated_at | 索引维护时间 |

写入流程：

```text
创建/更新 Note
  -> 清洗文本
  -> 按段落/token 切 chunk
  -> 计算 content_hash
  -> 内容变化才重新 embedding
  -> upsert 到向量库
  -> 删除旧 chunk
```

查询流程：

```text
用户问题 + 短期记忆
  -> 可选 query rewrite
  -> query embedding
  -> vector topK
  -> keyword topK
  -> merge + dedupe
  -> rerank
  -> 按 token 预算组装上下文
  -> LLM answer
```

生产环境必须注意：

- `owner_id` 必须参与过滤，防止跨用户召回。
- embedding 和 LLM 可以是两个模型，embedding 模型要稳定，频繁更换会导致旧向量不可比。
- chunk 不能太大，否则召回不准；也不能太小，否则上下文碎片化。
- 向量库只解决召回，不保证答案正确，仍要在 prompt 中要求“只基于提供上下文引用”。
- 需要记录命中的 chunk id、score 和来源，便于排查 hallucination 和召回质量。

### 10.7 为什么要有 Mock 降级

- 没有 API Key 时仍可以联调注册、鉴权、Notes 检索、会话和消息入库。
- 自动化测试不必依赖外部网络和付费 API。
- 外部模型故障时可以返回可理解的降级结果。

当前 Mock 主要用于开发。生产环境应明确标记降级状态，不应让用户误以为 Mock 是模型真实回答。

## 11. 核心 API

普通 JSON API 使用统一的泛型响应 `{data, code, message}`。成功业务码为 200；HTTPException、参数校验异常和未处理异常由全局处理器转换为相同结构。SSE 保留事件协议，流内错误携带 `code/message`。

| 方法 | 路径 | 是否鉴权 | 用途 |
| --- | --- | --- | --- |
| GET | `/health` | 否 | 存活检查 |
| POST | `/auth/register` | 否 | 用户注册 |
| POST | `/auth/login` | 否 | 登录并获取 JWT |
| GET | `/users/me` | 是 | 查询当前用户 |
| POST | `/notes` | 是 | 创建笔记 |
| GET | `/notes` | 是 | 查询笔记，可带 keyword |
| GET | `/notes/{note_id}` | 是 | 查询单条笔记 |
| PUT | `/notes/{note_id}` | 是 | 更新笔记 |
| DELETE | `/notes/{note_id}` | 是 | 删除笔记 |
| POST | `/agent/chat` | 是 | Agent 问答 |
| POST | `/agent/chat/stream` | 是 | SSE 文本/表单消息 |
| POST | `/agent/forms/note` | 是 | 幂等提交创建笔记表单 |
| GET | `/agent/sessions/{session_id}/messages` | 是 | 查询会话消息 |

## 12. HTTP 状态码设计

- `200 OK`：当前普通 JSON 成功接口统一返回 200，并用 `{data, code, message}` 作为响应信封。
- `401 Unauthorized`：token 缺失、无效、过期或登录失败。
- `404 Not Found`：资源不存在或不属于当前用户。
- `409 Conflict`：注册邮箱已存在。
- `422 Unprocessable Entity`：Pydantic/FastAPI 参数校验失败。

生产化可以进一步细化成功状态码，例如创建返回 `201 Created`、删除返回 `204 No Content`。当前项目为了前端统一解析，创建、删除等成功结果也包装为统一响应体。

## 13. 项目中实际解决的问题

### 13.1 `EmailStr` 缺少可选依赖

现象：导入 Pydantic Schema 时提示缺少 `email_validator`。

原因：`EmailStr` 的邮箱语法校验依赖额外包，但原始 `requirements.txt` 没有显式声明。

处理：将 `email-validator` 固定在依赖清单中，避免“本机恰好有所以能跑”的隐式依赖。

面试可说：

> 我会用全新虚拟环境安装并做 import/startup 验证，因为这能发现开发机已经安装、但未声明在项目里的隐式依赖。

### 13.2 Passlib 与 bcrypt 5 不兼容

现象：应用能启动，MySQL 表能创建，但真实注册时在密码哈希阶段返回 500。

原因：`passlib 1.7.4` 与新安装的 `bcrypt 5.0.0` 存在 API/行为兼容问题。仅调用 `/health` 无法发现，因为健康接口不执行密码哈希。

处理：显式固定 `bcrypt==4.0.1`，重启进程后再执行注册、数据库查询和登录验证。

面试可说：

> 健康检查成功不代表核心业务可用。接入 MySQL 后不仅要验证端口和 `SELECT 1`，还要跑注册、登录、Notes 写入这类真实业务链路，因为依赖冲突或事务问题通常只有走到核心代码才会暴露。

## 14. 可能的面试追问与参考回答

### 14.1 为什么 Schema 和 ORM Model 要分开？

> ORM Model 描述数据如何存储，Schema 描述 API 允许客户端输入和输出什么。如果直接对外暴露 ORM Model，容易泄露 `hashed_password` 等内部字段，也会让 API 合同和数据库结构强耦合。分开后可以对创建、更新、读取定义不同 Schema。

### 14.2 Session 为什么不做全局单例？

> SQLAlchemy Session 表示一组数据库操作和单位工作，它不适合被多个并发请求共享。项目通过 `get_db()` 每个请求创建一个 Session，请求完成后在 `finally` 中关闭。Engine 和连接池可以全局复用，Session 不应跨请求共享。

### 14.3 `commit()` 和 `refresh()` 有什么区别？

> `commit()` 提交当前事务；`refresh(obj)` 从数据库重新加载对象，使自增 ID、数据库默认时间等值反映到 ORM 对象上。

### 14.4 为什么用 `db.scalar(select(...))`？

> 这是 SQLAlchemy 2.x 风格。`select(User)` 构建查询，`db.scalar(...)` 返回第一行的第一个 ORM 对象，适合按唯一 email 查找用户。多条结果则使用 `db.scalars(query)` 后转成 list。

### 14.5 当前 Agent 为什么使用同步生成器？

> 当前 SQLAlchemy Session 和 Anthropic SDK 都使用同步 API，StreamingResponse 会在线程池中迭代同步生成器，模型每产出一段文本就立即发送 SSE。高并发场景可以整体切换 AsyncSession 和异步模型 SDK，不能只把函数改成 `async def` 却继续调用阻塞 IO。

### 14.6 这个项目如何防止水平越权？

> 每个受保护接口都从 JWT 获得当前用户，不接受客户端传入的 `owner_id`。创建资源时由服务端填入当前用户 ID，查询、更新、删除时都检查 `owner_id`。Agent Session 也会做相同校验。

### 14.7 MySQL 连不上时怎么排查？

> 我会按层排查：先确认 mysqld 是否监听 3306；再用 MySQL Client 和应用账号直连，排除账号、密码、Host 和权限问题；然后检查 URL 特殊字符编码和驱动是否安装；最后看 SQLAlchemy 异常链和 MySQL 日志。如果 Client 能连而应用不能，问题通常在连接字符串、驱动或进程未重载配置。

### 14.8 如何确保两条消息一致入库？

> AgentService 使用两个短事务：先提交 session 和 user message，再结束 Notes 只读事务，然后调用外部模型，最后另开事务保存 assistant message。这样不会在等待模型时长期占用 MySQL 事务。如果模型失败，会保留 user message 表示未回答状态；进一步可给消息增加 `pending/failed/completed` 状态和幂等键。

### 14.9 为什么不把模型 API Key 写在代码中？

> 密钥属于运行时配置，不应进入代码仓库。项目通过 Pydantic Settings 从 `.env` 加载。正式环境应使用 Secret Manager 或容器密钥注入，并定期轮换。

### 14.10 如果 Notes 数据量很大怎么优化？

> 首先不能像 Demo 这样每次把当前用户全部 Notes 拉到进程内临时建索引，要把 chunk 和 embedding 持久化到向量库或支持向量索引的数据库里。关键词检索可用 MySQL Full-Text Index 或 Elasticsearch，语义检索用向量 topK，再做 merge、dedupe、rerank 和 Token 预算控制。还要按 `owner_id` 做强过滤，避免跨用户召回。

## 15. 当前局限与生产化改进

面试中主动说出局限会显得更真实。可以按优先级这样说：

### P0：安全和正确性

1. 修改默认 `SECRET_KEY`，通过密钥管理系统注入。
2. 增加 refresh token、撤销机制和登录限流。
3. 将 `role` 改为 Enum 或数据库 Check Constraint。
4. 增加事务失败、唯一键冲突和 Agent 分段提交的自动化测试。
5. 给 Agent 调用增加超时、重试、并发限制和成本上限。

### P1：可运维性

1. 将 Alembic 迁移检查和 `alembic check` 加入 CI。
2. 增加结构化日志、request ID、指标和链路追踪。
3. `/health/live` 只检查进程，`/health/ready` 检查 MySQL 和必要依赖。
4. 增加配置校验，禁止生产环境使用默认密钥。
5. Docker 化并使用 CI 执行测试和依赖安全检查。

### P2：性能和体验

1. Notes 列表和消息列表增加分页。
2. 为 SSE 增加心跳、客户端主动取消和断线恢复策略。
3. 将高并发 IO 链路统一改为 async，或将长任务放入任务队列。
4. 对热点读取和限流状态使用 Redis。
5. 将关键词 LIKE 检索升级为混合检索和 rerank。

## 16. 测试策略

### 16.1 单元测试

- `hash_password` 生成的值不等于明文，`verify_password` 正反例正确。
- JWT 有效、过期、篡改和缺少 `sub` 的场景。
- `retrieve_notes` 的命中、fallback 和用户隔离。
- Pydantic Schema 的 email、长度和部分更新校验。

### 16.2 API 集成测试

1. 注册成功和 email 重复。
2. 登录成功和错误密码。
3. 不带 token、错误 token 和过期 token。
4. Notes 完整 CRUD。
5. A 用户不能访问 B 用户的 Note 和 Session。
6. Agent Mock/真实流的事件顺序、used_notes 和消息入库。
7. 表单意图只命中白名单、提交鉴权、重复提交幂等和完成状态恢复。

### 16.3 数据库测试

- 测试库与开发库隔离。
- 每个测试使用事务回滚或独立 fixture 清理数据。
- 至少在 CI 中对 MySQL 方言运行集成测试，不要只用 SQLite 代替，因为两者在类型、约束和并发行为上有差异。

## 17. 现场演示顺序

Swagger 地址：`http://127.0.0.1:8000/docs`

1. 调用 `GET /health`，说明应用已启动。
2. 调用 `POST /auth/register` 创建用户。
3. 在 Swagger 的 Authorize 中输入 email 和密码完成鉴权。
4. 调用 `GET /users/me`，证明 JWT 能获取当前用户。
5. 创建两条和 Python/RAG 相关的 Note。
6. 调用 `GET /notes?keyword=RAG`，展示用户数据检索。
7. 打开 React 页面提问，展示 SSE 文本逐段出现和引用 Notes。
8. 发送“帮我创建一条笔记”，在聊天内填写并提交表单。
9. 切到 Notes 页面确认新笔记，再刷新会话证明表单消息已入库。

演示时不要展示 `.env` 中的真实密码或 API Key。

## 18. 面试结尾总结

> 这个项目的重点不是功能数量，而是把一条完整的 AI 后端链路跑通：有 API 合同、用户鉴权、数据隔离、MySQL 持久化、Alembic 版本迁移、Agent 状态编排、外部模型降级和会话记录。我也在真实接入中解决了隐式依赖和版本兼容问题。如果进一步生产化，我会优先做安全密钥管理、测试、可观测性和完整 RAG 检索。

## 19. 复习清单

面试前确保能脱稿回答：

- 能用 30 秒和 2 分钟两种长度介绍项目。
- 能画出 Route、Schema、Service、CRUD、ORM、MySQL 的调用链路。
- 能说清 bcrypt 和 JWT 分别解决什么问题。
- 能说清 `owner_id` 如何防止水平越权。
- 能说清 Session、commit、refresh 和 rollback。
- 能说清 SQLite 切换 MySQL 时改了什么。
- 能区分 `create_all` 和 Alembic Migration。
- 能说清 AgentState、节点、边、SSE 流式调用和 Mock 降级。
- 能说清短期记忆、长期知识记忆、混合 RAG 和生产向量库升级方案。
- 能说出至少 3 个当前局限和对应改进方案。
