# Fieldnote AI Agent

一个面向个人知识管理场景的全栈 AI Agent 项目。后端使用 FastAPI、LangGraph、MySQL、Qdrant、FastEmbed 和 Anthropic Messages 兼容模型服务，前端使用 React、TypeScript、Vite 与 Ant Design X。

项目不只是一次模型调用 Demo：它覆盖认证、用户数据隔离、知识笔记 CRUD、文档导入与异步向量化、RAG、会话记忆、SSE 流式输出、文件/OCR/图片分析、结构化表单、私有附件以及容器化生产部署。

配套前端位于 `../agent-frontfond`。

腾讯云实际部署、故障排查和面试讲解见 [docs/tencent-cloud-deployment-guide.md](docs/tencent-cloud-deployment-guide.md)。

## 1. 项目亮点

- JWT 登录认证；密码只保存 bcrypt 哈希。
- Service 层统一处理权限、幂等、事务和跨模块流程。
- 笔记按 500 字符、80 字符重叠窗口切块。
- FastEmbed 使用 `BAAI/bge-small-zh-v1.5` 生成中文语义向量。
- Qdrant 持久化分块向量，并用 `owner_id` payload filter 保证多租户隔离。
- Qdrant 为 `owner_id`、`note_id` 建立 payload index，避免数据量增长后过滤退化为全量扫描。
- 笔记新增、更新、删除后同步维护向量索引；支持一键全量重建。
- 笔记事务与索引任务写入同一个 MySQL 事务；独立 `knowledge-worker` 消费 Outbox，失败指数退避并最多重试 6 次。
- 全量 reindex 改为异步任务，接口立即返回任务 ID，可查询 pending/processing/completed/failed 状态。
- Qdrant 暂时不可用时自动回退到本地关键词 + 哈希向量混合检索。
- 向量召回应用 `0.55` 最低相关度阈值，避免 Top-K 在全部不相关时仍产生虚假引用。
- 只将真实召回的笔记传给模型，引用来源由服务端产生并保存快照。
- LangGraph 显式编排“检索知识 → 组织上下文 → 模型生成”流程。
- LangGraph 模型节点带指数退避重试；向量候选按 75% 语义分 + 25% 关键词分混合重排。
- SSE 逐段返回 `session/sources/delta/form/done/error` 事件。
- 模型调用期间不长期占用数据库连接和事务。
- 支持 PDF、DOCX、TXT、Markdown、CSV、图片 OCR 与视觉模型分析；知识笔记页可直接导入文档并建立向量索引。
- 附件存储支持阿里云 OSS 和本地持久卷；对象键按用户隔离，使用短期签名 URL，长期密钥不进入浏览器。
- Docker Compose 提供 MySQL、Qdrant、迁移任务、API 和独立知识索引 Worker。
- `/health` 用于存活检查，`/ready` 同时检查 MySQL 与已启用的 Qdrant。
- 每个响应携带 `X-Request-ID`，提供 Prometheus `/metrics`、路由级基础限流，以及 API/RAG/模型/Worker JSON 日志和 Docker 日志轮转。
- 笔记、问题和上传文件均有服务端硬限制，上传采用分块读取，在超过 10 MB 时提前终止。

## 2. 技术栈

| 分类 | 技术 | 用途 |
| --- | --- | --- |
| Web | FastAPI、Uvicorn | REST API、依赖注入、SSE、Swagger |
| 数据合同 | Pydantic v2 | 输入校验、响应裁剪、配置校验 |
| 关系数据库 | SQLAlchemy 2、Alembic、MySQL/SQLite | 用户、笔记、会话、消息和事务 |
| 向量知识库 | FastEmbed、Qdrant | 分块、Embedding、持久化和语义召回 |
| Agent | LangGraph、Anthropic SDK | 状态图编排和模型协议适配 |
| 文件能力 | pypdf、OpenXML、Pillow、Tesseract | 文档解析、OCR 和图片分析 |
| 附件存储 | 阿里云 OSS / Docker 持久卷 | 私有附件、签名预览、归属校验 |
| 部署 | Docker、Compose、Nginx | 服务编排、迁移、健康检查、HTTPS/SSE 代理 |
| 前端 | React、TypeScript、Vite、Ant Design X | 聊天、笔记、引用、附件和表单 UI |

## 3. 架构

```text
Browser / React
       |
       | REST + JWT + SSE
       v
FastAPI Route
       |
       v
Service: 权限、事务、幂等、业务编排
  |          |             |             |
  v          v             v             v
MySQL     LangGraph     Qdrant          OSS
业务数据   Agent 状态图   分块向量         私有附件
                         ^
                         |
                    FastEmbed
```

后端分层：

```text
app/main.py          HTTP 路由、依赖注入、SSE 响应
app/schemas.py       Pydantic 请求/响应合同
app/services.py      权限、事务、索引同步、应用流程
app/crud.py          SQLAlchemy 查询与对象增删
app/models.py        关系数据模型
app/agent.py         LangGraph 与模型调用
app/rag.py           本地混合检索降级实现
app/vector_store.py  切块、FastEmbed、Qdrant 适配
app/file_parser.py   PDF/DOCX/文本/OCR 解析
app/storage.py       OSS/本地持久卷与签名 URL
app/logging_config.py JSON 日志格式与请求关联上下文
```

## 4. 知识库与 RAG 流程

### 4.1 写入流程

```text
创建/更新笔记
  -> MySQL 写入业务数据
  -> 同一 MySQL 事务写入 knowledge_index_jobs Outbox
  -> 提交事务
  -> 标题 + 正文切块（500，overlap 80）
  -> FastEmbed 生成中文语义向量
  -> knowledge-worker 领取任务
  -> FastEmbed + Qdrant upsert
  -> payload 保存 owner_id、note_id、chunk_index、title、chunk
```

删除笔记时在同一事务写入 delete 任务，Worker 再按 `owner_id + note_id` 删除对应向量。MySQL 是真实数据源；Worker 崩溃后会回收超过 10 分钟的 processing 租约，任务失败采用指数退避，连续 6 次失败后标记为 failed。可调用 `POST /knowledge/reindex` 异步重建当前用户索引。

### 4.2 查询流程

```text
用户问题
  -> FastEmbed 生成 query vector
  -> Qdrant 按 owner_id 过滤并召回候选分块
  -> 丢弃相似度低于 0.55 的候选
  -> 语义分 75% + 关键词分 25% 混合重排
  -> 按 note_id 去重并取 Top-K
  -> 再从 MySQL 按 owner_id 查询笔记
  -> 仅将每篇笔记的最佳命中分块放入 RAG context
  -> 模型流式回答
  -> 保存答案与引用快照
```

安全边界有两层：Qdrant payload filter 限制当前用户，MySQL 查询再次校验 `owner_id`。即使向量 payload 配错，也不会将其他用户笔记返回给模型。模型系统提示还明确把笔记内容视为不可信数据，降低知识库文本中提示注入指令的影响。

### 4.3 降级策略

本地开发默认 `VECTOR_STORE_ENABLED=false`，使用关键词重叠 + 本地哈希向量检索，方便零依赖启动。生产默认启用 Qdrant。Qdrant 请求失败时会记录完整服务端日志并回退本地检索，聊天功能仍可用，但召回质量与性能会下降。

## 5. Agent 编排是否完整

项目已经包含可运行的 LangGraph 编排，不是只安装了依赖：

```text
START
  -> retrieve_notes：调用注入的检索器，获取当前用户真实笔记
  -> generate_answer：拼接会话记忆、问题和知识上下文，调用模型
  -> END
```

同步 `/agent/chat` 走完整 LangGraph 状态图。前端使用的 `/agent/chat/stream` 为了直接转发 token 增量，复用相同的检索函数与生成函数，但由 Service 控制 SSE 生命周期和消息持久化。结构化“创建笔记”意图会进入受控表单分支，不执行模型生成的任意工具调用。

当前编排属于确定性工作流，而不是开放式自治 Agent。生产扩展可以增加意图路由、工具执行、审核节点、重试、checkpoint、人工确认和任务队列；面试时不要把这些后续方向说成已经实现。

## 6. 本地启动

要求 Python 3.12+、Node.js 20+。仅聊天和 CRUD 可以不启动 Qdrant。

后端：

```bash
cd python-agent-demo
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd ../agent-frontfond
npm install
npm run dev
```

- 前端：http://127.0.0.1:5173
- API：http://127.0.0.1:8000
- Swagger：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

如果本地也要验证真实向量库，启动 Qdrant，将 `.env` 中 `VECTOR_STORE_ENABLED=true`，同时启动 `python -m app.knowledge_worker`，再调用 `POST /knowledge/reindex`。

## 7. 关键配置

模型服务使用 Anthropic Messages 兼容协议：

```env
ANTHROPIC_AUTH_TOKEN=replace-me
ANTHROPIC_BASE_URL=https://your-anthropic-compatible-provider.example.com
ANTHROPIC_MODEL=your-model-name
ANTHROPIC_VISION_MODEL=your-vision-model-name
API_TIMEOUT_MS=600000
```

向量知识库：

```env
VECTOR_STORE_ENABLED=true
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=replace-with-a-long-random-key
QDRANT_COLLECTION=note_chunks
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_CACHE_DIR=/opt/fastembed-cache
EMBEDDING_LOCAL_FILES_ONLY=true
EMBEDDING_MODEL_PATH=/opt/fastembed-cache/fast-bge-small-zh-v1.5
RAG_TOP_K=5
RAG_CANDIDATE_LIMIT=12
RAG_VECTOR_SCORE_THRESHOLD=0.55
RATE_LIMIT_ENABLED=true
METRICS_ENABLED=true
```

附件存储（生产可选 OSS，本地开发可使用 `auto`）：

```env
ATTACHMENT_STORAGE_BACKEND=oss
OSS_ACCESS_KEY_ID=replace-me
OSS_ACCESS_KEY_SECRET=replace-me
OSS_ENDPOINT=https://oss-cn-your-region.aliyuncs.com
OSS_BUCKET=your-private-bucket
OSS_OBJECT_PREFIX=ai-agent-demo
OSS_SIGNED_URL_EXPIRE_SECONDS=3600
```

AccessKey 只能放在未纳入版本控制的 `.env`/`.env.production` 中。未配置 OSS 且使用 `auto` 时，系统回退到 `/data/uploads`；Compose 使用 `upload_data` 卷持久化附件。

更换 `EMBEDDING_MODEL` 后向量维度或语义空间可能变化，应更换 collection 名或删除旧 collection，再执行全量 reindex。

## 8. 生产部署检查与步骤

当前 Compose 是单机生产基线，适合面试演示、小流量服务或进一步接入云基础设施。它已具备：

- MySQL 8.4 持久卷和健康检查。
- 独立 `migrate` 一次性任务，成功后才启动 API。
- Qdrant 固定版本和持久卷，仅绑定宿主机回环地址 `127.0.0.1:6333`，便于本机备份且不暴露公网。
- 独立 `knowledge-worker` 消费向量 Outbox，不在 API 请求中执行全量 reindex。
- API 非 root 用户、多 worker、就绪检查、自动重启。
- API 仅绑定宿主机 `127.0.0.1:8000`，必须由 Nginx/云负载均衡对外提供 HTTPS。
- 镜像构建时预下载 embedding 模型，避免首请求下载。
- 生产配置启动校验：弱 `SECRET_KEY`、SQLite、空模型密钥、空 Qdrant 密钥会拒绝启动。

部署命令：

```bash
cp .env.production.example .env.production
# 修改所有 replace-with-* 和第三方密钥
docker compose --env-file .env.production config
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d
docker compose --env-file .env.production ps
curl http://127.0.0.1:8000/ready
```

首次上线或已有笔记迁移到 Qdrant 后，登录获取 JWT，再调用：

```bash
curl -X POST https://api.example.com/knowledge/reindex \
  -H "Authorization: Bearer YOUR_TOKEN"
```

接口返回任务 ID，随后查询：

```bash
curl https://api.example.com/knowledge/tasks/TASK_ID \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Nginx 示例位于 `deploy/nginx.conf.example`，其中关闭了 `proxy_buffering` 并将读取超时设为 650 秒，保证 SSE 不被缓存成一次性响应。

推荐同源部署：Nginx 的 `/` 提供前端静态文件，`/api/` 反向代理后端。若前后端必须分域，将前端完整 Origin 写入 `CORS_ALLOWED_ORIGINS`（多个值用英文逗号分隔），并将前端 `VITE_API_BASE_URL` 指向 API 域名；不要使用 `*`。

### 上线前必须完成

- 使用密码管理器生成至少 32 位随机 `SECRET_KEY`、MySQL 密码和 Qdrant API Key。
- 对已在聊天、截图或 Git 中出现过的模型/OSS 密钥立即轮换。
- 为域名配置 HTTPS，不直接公开 Uvicorn、MySQL 或 Qdrant 端口。
- 配置 MySQL 与 Qdrant 数据卷备份，并实际演练恢复。
- 限制服务器安全组，只开放 80/443 和必要的运维入口。
- 接入集中日志、错误告警、磁盘/内存监控和请求追踪。
- 根据 CPU/内存压测结果设置 `WEB_CONCURRENCY`；embedding 是 CPU 密集型，worker 越多内存占用越高。
- 应用已为注册、登录、上传、模型调用和 reindex 提供基础限流；多机部署仍需 Redis 或 API Gateway 统一限流与成本配额。
- 定时执行 `deploy/backup.ps1`，并将产物同步到异地对象存储；备份必须配套恢复演练。
- 多机部署时将 MySQL、Qdrant、OSS 迁移为高可用托管或集群方案。

单机 Compose 仍不是完整高可用架构：它没有自动备份、跨机容灾、WAF、限流服务、集中可观测性和滚动发布控制。这些需要由服务器或云平台补充。

## 9. API 概览

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET | `/health` | 进程存活检查 |
| GET | `/ready` | MySQL/Qdrant 就绪检查 |
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录并签发 JWT |
| GET | `/users/me` | 当前用户 |
| POST/GET | `/notes` | 创建/查询笔记 |
| POST | `/notes/import` | 解析文档、创建笔记并异步建立向量索引 |
| GET/PUT/DELETE | `/notes/{id}` | 笔记详情、更新、删除 |
| POST | `/knowledge/reindex` | 重建当前用户向量索引 |
| GET | `/knowledge/tasks/{id}` | 查询异步索引任务状态 |
| GET | `/metrics` | Prometheus 指标（Nginx 示例限制为本机访问） |
| POST | `/agent/chat` | LangGraph 同步问答 |
| POST | `/agent/chat/stream` | SSE 流式 RAG 问答 |
| POST | `/agent/files/analyze` | 文件/OCR/图片流式分析 |
| POST/DELETE | `/uploads` | 私有附件上传/删除（OSS 或本地持久卷） |
| POST | `/agent/forms/note` | 提交受控创建笔记表单 |
| GET | `/agent/sessions/{id}/messages` | 恢复聊天历史 |

## 10. 数据与事务设计

- `users`：账号、密码哈希、创建时间。
- `notes`：知识笔记，通过 `owner_id` 隔离用户。
- `agent_sessions`：对话会话。
- `agent_messages`：文本、引用快照、附件和结构化表单 JSON。
- Qdrant `note_chunks`：向量与最小检索 payload，不作为业务真实数据源。

CRUD 层不主动提交事务；Service 决定 commit/rollback。流式问答先短事务保存用户消息，再释放连接执行耗时模型调用，最后用短事务保存完整答案，避免 SSE 持续数分钟时占住连接池。

## 11. 文件解析、Chat 附件与知识库导入

- TXT/Markdown/CSV 优先使用 UTF-8（含 BOM），并兼容 GB18030。
- PDF 使用 pypdf 提取前 100 页文本层；加密 PDF 拒绝处理。扫描 PDF 尚未实现逐页转图片 OCR。
- DOCX 直接读取 OpenXML 段落与表格文本节点。
- 图片用 Pillow 校正方向、限制像素并压缩，Tesseract 执行中英文 OCR；配置视觉模型时可发送 Anthropic image 内容块。
- 上传大小和类型在服务端限制，不能只相信前端校验。
- 上传按 1 MB 分块读取，累计超过 10 MB 立即返回 413，避免先无限读入内存再校验。
- 图片最多 2500 万像素，视觉输入最长边压缩到 1568 像素，提取文本最多 60000 字符。
- 附件对象键带用户目录前缀；签名、删除、分析都会再次校验归属。
- 数据库保存稳定 `object_key`，读取历史时重新生成短期 URL。

Chat 回形针与知识笔记导入是两条不同业务链路：

```text
Chat 回形针：上传私有附件 -> 服务端解析/OCR -> 模型分析 -> SSE 返回
知识笔记导入：解析文档 -> 创建 Note + Outbox -> Worker 切块/Embedding -> Qdrant
```

Chat 附件默认不会进入 Qdrant，避免临时文件未经用户确认就污染长期知识库。只有知识笔记页的“导入文档”或普通笔记保存操作才会触发向量索引。

## 12. 面试介绍

### 30 秒版本

> 我做了一个 FastAPI + React 的个人知识库 Agent。后端用 JWT、SQLAlchemy 和 Alembic 管理多用户笔记及会话；知识库会把笔记重叠切块，用 FastEmbed 生成中文向量并写入 Qdrant，查询时按用户过滤做语义召回，再通过 LangGraph 编排检索和模型生成，并用 SSE 流式返回答案及真实引用。项目还支持文件/OCR/视觉分析、OSS 私有附件和聊天内受控表单，生产侧用 Docker Compose 编排 MySQL、Qdrant、迁移任务与多 worker API。

### 2 分钟展开顺序

1. 先说业务：个人笔记进入知识库，聊天时优先用自己的资料回答。
2. 再说分层：Route、Schema、Service、CRUD、Agent、Vector Store、Storage。
3. 重点说 RAG：切块、Embedding、Qdrant、多租户过滤、Top-K、真实引用、降级与 reindex。
4. 说 Agent：LangGraph 两节点确定性编排，流式路径复用节点能力，Service 管 SSE 生命周期。
5. 说工程：JWT、事务边界、幂等表单、文档解析、OSS 权限、短期签名 URL、统一错误响应。
6. 最后说生产：MySQL/Qdrant 持久化、迁移先行、就绪探针、非 root、Nginx HTTPS/SSE、备份监控边界。

### 常见追问

**为什么用 Qdrant？** 关系库负责强一致业务数据，Qdrant 专注高维相似度搜索、payload filter 和 Top-K 召回，职责清晰；后续也便于独立扩容。

**如何保证多用户隔离？** JWT 得到当前用户；所有 MySQL 查询校验 `owner_id`；Qdrant 查询也强制 `owner_id` filter；召回后回表再校验一次。

**向量库写失败怎么办？** MySQL 是真实数据源，业务事务同时写 Outbox；独立 Worker 重试 Qdrant 操作，查询可降级，运维也能异步 reindex。更大规模可把数据库 Outbox 通过 CDC 投递 Kafka，并增加死信队列和告警。

**为什么切块有 overlap？** 避免语义跨边界被截断。当前字符切块实现简单稳定；生产可升级为 Markdown 结构/token 切块，并用离线评测优化 chunk size、Top-K 与 rerank。

**LangGraph 是否只是装了包？** 不是，同步问答实际编译并执行 `retrieve_notes -> generate_answer` 状态图。当前是可解释的确定性工作流，不夸大成开放式自主 Agent。

**为什么 SSE 而不是 WebSocket？** 业务主要是服务端单向增量输出；SSE 协议简单。使用 `fetch` 解析 SSE，因为请求需要 POST JSON 和 Authorization Header。

**Chat 上传的文档会进入向量库吗？** 不会。Chat 附件只做当前会话分析；用户明确在知识笔记页导入后，系统才创建 Note，通过 Outbox Worker 切块、Embedding 并写入 Qdrant。

**生产还缺什么？** 单机版缺跨机高可用、自动备份、WAF/限流、集中可观测性和灰度发布；README 已给出明确上线清单，避免把演示部署误称为大型生产架构。

## 13. 测试与检查

```bash
python -m compileall -q app
python -m unittest discover -s tests -v
alembic upgrade head
docker compose --env-file .env.production config
```

当前单元测试共 18 项，覆盖 HTTP/SSE 合同、限流、上传大小、Outbox 原子性、Worker、向量阈值/租户过滤和本地附件签名校验；前端使用 `npm run build` 执行 TypeScript 与生产构建检查。

### 量化证据

可复现工具：

```bash
python deploy/load_test.py --url http://127.0.0.1:8000/health --requests 1000 --concurrency 10
python deploy/rag_eval.py --model-path /opt/fastembed-cache/fast-bge-small-zh-v1.5 --threshold 0.55
./deploy/ops_check.sh
./deploy/backup.sh /opt/fieldnote/backups
./deploy/verify_backup.sh /opt/fieldnote/backups/BACKUP_TIMESTAMP
```

腾讯云实测、阈值对比和限制说明见 [docs/evidence/README.md](docs/evidence/README.md)。当前本机 API 健康接口基线为 1000 请求/10 并发、0 错误、524.6 RPS、P95 22.5 ms；RAG 小型标注集在阈值 0.55 时 Recall@3 为 0.75、MRR 为 0.9375、无答案误引用率为 0。健康接口结果不代表模型 Chat 容量，小型评测集也不构成检索质量承诺。

服务器使用 systemd timer 每日备份、每 5 分钟执行运行检查：

```bash
systemctl list-timers 'fieldnote-*'
journalctl -u fieldnote-backup.service
journalctl -u fieldnote-ops-check.service
```

生产构建会下载并固化 embedding 模型，因此第一次构建较慢、镜像也会增大。若部署环境不允许构建时访问模型仓库，应在 CI 中构建并推送镜像，服务器只拉取经过验证的镜像。

## 14. 当前仍需完善的方向

以下项目经过审查后仍属于明确的后续工作，不应在面试中描述为已经完成：

1. **消息基础设施升级**：当前已实现数据库事务 Outbox、独立 Worker、租约恢复和指数退避。多机高吞吐场景可进一步使用 CDC + Kafka/RabbitMQ、独立死信队列和任务积压告警。
2. **检索质量评测**：目前已实现向量召回、关键词混合重排与本地降级，但还没有离线标注集、Recall@K、MRR、答案忠实度评测和 cross-encoder reranker。
3. **编排持久化**：LangGraph 已有节点重试，但还没有持久化 checkpoint、人工审核和跨进程长任务恢复。复杂工具 Agent 应增加共享 checkpoint store 和 human-in-the-loop。
4. **异步任务范围**：reindex 和笔记 embedding 已进入 Worker；文件 OCR 与视觉分析仍在 API 进程，大文件/批处理应进一步迁移到任务队列。
5. **分布式限流与配额**：当前有应用级基础限流，但多 worker/多机下应使用 Redis 或 API Gateway 统一计算用户并发、速率和模型成本配额。
6. **深度可观测性**：当前已有 request ID、Prometheus 请求量/延迟、模型 TTFT/Token、Qdrant 命中与耗时、Worker 状态 JSON 日志；仍需 OpenTelemetry trace、集中日志平台、SSE 中断指标和自动告警规则。
7. **高可用与灾备**：已有 MySQL dump、Qdrant snapshot 脚本基线；生产仍需要异地存储、自动调度、恢复演练、托管/集群数据库、滚动发布和容量压测。
8. **测试覆盖**：当前覆盖 HTTP/SSE 合同、基础限流、Outbox 原子提交/回滚、向量切块/阈值/租户过滤和本地附件签名；仍需真实 MySQL/Qdrant/OSS 集成测试、鉴权越权、Worker 崩溃恢复和端到端测试。
