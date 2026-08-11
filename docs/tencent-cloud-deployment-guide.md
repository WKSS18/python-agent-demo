# 腾讯云单机部署复盘与面试讲解

## 1. 部署结果

本项目已部署到腾讯云 CVM，采用单机容器化方案：

- 前端：React + TypeScript + Vite，构建为静态文件，由 Nginx 提供访问。
- 后端：FastAPI + Uvicorn，运行在 Docker 容器中，仅监听宿主机 `127.0.0.1:8000`。
- 业务数据库：MySQL 8.4，数据保存在 Docker Volume。
- 向量数据库：Qdrant 1.18.3，数据保存在 Docker Volume。
- 异步任务：独立 Knowledge Worker 消费知识索引 Outbox。
- 网关：Nginx 对外开放 HTTP，并将 `/api/` 反向代理到 FastAPI。
- 数据库迁移：Alembic 在 API 启动前自动执行。

当前是适合演示、小流量服务的单机生产基线，不是高可用集群。

## 2. 整体请求链路

```text
浏览器
  │
  ├── GET /、/assets/* ──> Nginx ──> React 静态文件
  │
  └── /api/* ───────────> Nginx ──> FastAPI
                                      │
                                      ├── MySQL：用户、笔记、会话、消息、Outbox
                                      ├── Qdrant：知识笔记向量检索
                                      ├── Knowledge Worker：异步建立/更新向量索引
                                      └── Anthropic 兼容模型接口：流式生成回答
```

Nginx 是唯一公网入口。MySQL、Qdrant 和 FastAPI 不直接暴露到公网，降低攻击面。

## 3. 服务器准备

本次服务器环境：

```text
系统：Ubuntu Server 26.04 LTS 64 位
CPU：2 核
内存：2 GB
磁盘：约 50 GB
```

安装基础软件：

```bash
sudo apt update
sudo apt install -y git nginx docker.io docker-compose-v2
sudo systemctl enable --now docker nginx
sudo usermod -aG docker ubuntu
```

验证：

```bash
docker version
docker compose version
nginx -v
```

腾讯云安全组只需开放：

- `22`：SSH 运维，建议限制来源 IP。
- `80`：HTTP。
- `443`：配置域名和 HTTPS 后开放。

不要向公网开放 `3306`、`6333` 和 `8000`。

## 4. SSH 登录与部署授权

先使用 Ubuntu 用户名和服务器密码登录：

```bash
ssh ubuntu@服务器公网IP
```

为了自动部署，不在聊天、脚本或 Git 仓库中传递服务器密码，而是将本机 SSH 公钥加入服务器：

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" |
  ssh ubuntu@服务器公网IP "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys"
```

验证公钥登录：

```bash
ssh -o PasswordAuthentication=no ubuntu@服务器公网IP "whoami; hostname"
```

这种方式不影响原有用户名密码登录，同时避免在部署过程中泄露密码。

## 5. 获取项目代码

后端和前端是两个公开 GitHub 仓库，目标目录为：

```text
/opt/fieldnote/python-agent-demo
/opt/fieldnote/agent-frontfond
```

正常情况下使用：

```bash
sudo mkdir -p /opt/fieldnote
sudo chown ubuntu:ubuntu /opt/fieldnote
cd /opt/fieldnote

git clone --branch main --single-branch 后端仓库地址 python-agent-demo
git clone --branch main --single-branch 前端仓库地址 agent-frontfond
```

本次腾讯云到 GitHub 的连接出现超时，因此实际采用了备用方案：在本地通过 `git bundle` 打包已提交的 `main` 分支，上传服务器后克隆，再把 `origin` 恢复为 GitHub 地址。这样不会上传 `.env`、虚拟环境、日志和本地数据库，也保留了完整 Git 历史。

## 6. 生产环境变量

从模板创建生产配置：

```bash
cd /opt/fieldnote/python-agent-demo
cp .env.production.example .env.production
chmod 600 .env.production
```

关键配置分为四类：

### 6.1 应用安全

```dotenv
APP_ENV=production
SECRET_KEY=至少32位随机字符串
WEB_CONCURRENCY=1
```

随机值可通过以下命令生成：

```bash
openssl rand -hex 32
```

由于服务器只有 2 GB 内存，本次将 Uvicorn Worker 数量设为 1，避免多个进程重复加载模型造成内存压力。

### 6.2 MySQL

```dotenv
MYSQL_DATABASE=ai_agent_demo
MYSQL_USER=ai_agent_app
MYSQL_PASSWORD=强随机密码
MYSQL_ROOT_PASSWORD=另一个强随机密码
DATABASE_URL=mysql+pymysql://ai_agent_app:应用密码@mysql:3306/ai_agent_demo?charset=utf8mb4
```

密码、Token 和密钥只保存在服务器 `.env.production` 中，不能提交到 Git。

### 6.3 Qdrant 与 Embedding

```dotenv
VECTOR_STORE_ENABLED=true
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=强随机字符串
QDRANT_COLLECTION=note_chunks
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_CACHE_DIR=/opt/fastembed-cache
EMBEDDING_LOCAL_FILES_ONLY=true
EMBEDDING_MODEL_PATH=/opt/fastembed-cache/fast-bge-small-zh-v1.5
RAG_VECTOR_SCORE_THRESHOLD=0.55
```

生产环境直接使用镜像内已经固化的 Embedding 模型路径，不在用户首次聊天时访问外部模型仓库。

### 6.4 大模型接口

```dotenv
ANTHROPIC_AUTH_TOKEN=模型平台生成的新Token
ANTHROPIC_BASE_URL=Anthropic兼容接口地址
ANTHROPIC_MODEL=实际模型名称
API_TIMEOUT_MS=600000
```

密钥一旦出现在聊天记录、终端历史或公开仓库中，应立即撤销并重新生成。

## 7. 后端镜像构建

项目原始 Dockerfile 包含以下步骤：

1. 使用 `python:3.12-slim` 基础镜像。
2. 安装 Tesseract OCR 和中文语言包。
3. 安装 Python 依赖。
4. 将中文 Embedding 模型固化进镜像。
5. 复制 Alembic 迁移和后端代码。
6. 创建非 root 用户运行 API。

腾讯云访问 Docker Hub、Debian、PyPI 和 Hugging Face 时出现过超时，因此做了以下适配：

- Docker 使用腾讯云镜像加速地址。
- Debian 软件包改用腾讯镜像。
- Python 包改用腾讯云 PyPI 镜像。
- Embedding 模型使用本地已有缓存上传并固化。
- 运行时设置 `EMBEDDING_MODEL_PATH`，完全绕开 Hugging Face 下载器。

部署专用 Dockerfile 位于：

```text
/opt/fieldnote/python-agent-demo/deploy/Dockerfile.tencent
```

构建命令：

```bash
cd /opt/fieldnote/python-agent-demo
docker build \
  --network=host \
  -f deploy/Dockerfile.tencent \
  -t python-agent-demo-api:latest \
  .
```

同一份应用镜像用于 API、迁移任务和 Knowledge Worker，只是启动命令不同：

```bash
docker tag python-agent-demo-api:latest python-agent-demo-migrate:latest
docker tag python-agent-demo-api:latest python-agent-demo-knowledge-worker:latest
```

## 8. Docker Compose 启动顺序

启动命令：

```bash
cd /opt/fieldnote/python-agent-demo
docker compose --env-file .env.production up -d --no-build
```

Compose 的依赖顺序是：

```text
MySQL 健康
  ↓
Alembic migrate 执行成功
  ↓
API + Knowledge Worker 启动

Qdrant 同时启动并挂载持久卷
```

检查状态：

```bash
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs -f --tail=200 api
curl http://127.0.0.1:8000/ready
```

`/health` 只表示进程存活；`/ready` 会检查数据库和启用的依赖，更适合上线验收。

## 9. 前端构建与 Nginx

前端在本地构建，减少 2 GB 云服务器的资源压力：

```bash
cd agent-frontfond
npm ci
npm run build
```

将 `dist/` 上传到：

```text
/var/www/fieldnote
```

Nginx 的核心配置：

```nginx
server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 12m;
    root /var/www/fieldnote;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 650s;
        proxy_send_timeout 650s;
    }
}
```

关键点：

- `try_files ... /index.html` 支持 React SPA 刷新回退。
- `/api/` 同源代理使前端无需处理跨域。
- SSE 必须关闭 `proxy_buffering`，否则增量回答可能被缓存到最后一次性返回。
- FastAPI 只绑定 `127.0.0.1:8000`，不能绕过 Nginx 公网访问。

验证并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 10. 实际问题与排查方法

### 10.1 GitHub 克隆超时

现象：`git clone` 长时间没有进度。

处理：本地使用 `git bundle` 携带完整提交历史上传服务器，再恢复 GitHub `origin`。

### 10.2 Docker Hub 无法连接

现象：拉取 `python:3.12-slim` 超时。

处理：为 Docker 配置腾讯云镜像加速，并重启 Docker 服务。

### 10.3 Debian/PyPI 下载慢

现象：镜像构建停在 `apt-get update` 或 `pip install`。

处理：部署专用 Dockerfile 切换到腾讯镜像，并使用 `--network=host` 构建。

### 10.4 聊天一直 loading

现象：`POST /agent/chat/stream` 已经返回 200，但页面长时间没有模型增量。

排查结果：请求卡在 RAG 的 Embedding 首次加载。虽然模型文件已在镜像中，FastEmbed 仍先访问不可达的 Hugging Face。

修复：

```dotenv
EMBEDDING_LOCAL_FILES_ONLY=true
EMBEDDING_MODEL_PATH=/opt/fastembed-cache/fast-bge-small-zh-v1.5
```

代码将 `specific_model_path` 传给 FastEmbed，完全绕开在线下载器。修复后：

- Embedding 测试从超过 2 分钟降到约 0.8 秒。
- 最小模型流式调用约 2 秒返回。

这个问题说明：构建时缓存了模型，不代表运行时一定不会联网；必须验证运行时实际加载路径。

### 10.5 不相关笔记被错误引用

现象：用户询问“目前前端前景”，知识库中只有 Python 测试笔记，但页面仍展示这条笔记为引用。

原因：向量检索原来只取 Top-K，没有最低相关性阈值。Top-K 只能表示“候选中最接近”，不代表结果真的相关；即使所有笔记都不相关，Qdrant 仍会返回分数最高的一条。

处理：增加 `RAG_VECTOR_SCORE_THRESHOLD=0.55`，在 Qdrant 查询和应用层同时过滤。低于阈值时不向模型提供笔记，也不在页面展示引用。实际样本中，不相关问题得分约 `0.41`，相关问题得分约 `0.75` 至 `0.78`。

### 10.6 Chat 上传提示“OSS 尚未配置”

现象：点击 Chat 回形针选择文件后，前端提示“OSS 尚未配置”。

原因：最初的附件存储实现只支持阿里云 OSS；服务器没有配置 AccessKey、Bucket 时，`POST /uploads` 会返回 503。文档解析代码没有故障，请求是在进入解析接口前的附件持久化阶段失败。

处理：增加可切换的附件存储策略。当前线上已配置私有阿里云 OSS，北京地域 Bucket 为 `wh-syyoss`，生产环境使用：

```dotenv
ATTACHMENT_STORAGE_BACKEND=oss
OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com
OSS_BUCKET=wh-syyoss
OSS_OBJECT_PREFIX=ai-agent-demo
OSS_SIGNED_URL_EXPIRE_SECONDS=3600
```

`OSS_ACCESS_KEY_ID` 和 `OSS_ACCESS_KEY_SECRET` 只保存在服务器权限为 600 的 `.env.production`，不能提交到 Git、部署文档或前端代码。系统也保留 `auto/local` 模式：没有 OSS 时可回退到 Docker `upload_data` 持久卷，并使用 HMAC 过期签名 URL 访问。

## 11. 上线验收清单

```bash
docker compose --env-file .env.production ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://服务器IP/api/ready
sudo nginx -t
free -h
df -h
```

浏览器侧验证：

1. 注册和登录。
2. 新建、修改和删除知识笔记。
3. 发起聊天并确认逐段流式显示。
4. 确认回答能够引用当前用户笔记。
5. 刷新页面后确认会话和 SPA 路由正常。
6. 检查容器日志中没有持续报错或重启。
7. 在 Chat 上传文档，确认出现“正在解析文档并准备分析”，随后收到流式回答。
8. 在知识笔记页导入文档，等待 Worker 完成索引后再提问，确认只引用相关笔记。

## 12. 后续更新流程

后端更新：

```bash
cd /opt/fieldnote/python-agent-demo
git pull --ff-only origin main
docker build --network=host -f deploy/Dockerfile.tencent -t python-agent-demo-api:latest .
docker tag python-agent-demo-api:latest python-agent-demo-migrate:latest
docker tag python-agent-demo-api:latest python-agent-demo-knowledge-worker:latest
docker compose --env-file .env.production up -d --no-build
curl http://127.0.0.1:8000/ready
```

前端更新：

```bash
npm ci
npm run build
sudo cp -a dist/. /var/www/fieldnote/
sudo nginx -t
sudo systemctl reload nginx
```

禁止执行：

```bash
docker compose down -v
```

`-v` 会删除 MySQL 和 Qdrant 数据卷，可能造成数据丢失。

## 13. 备份与生产化改进

当前仍需要补充：

- 为 MySQL 和 Qdrant 配置自动备份及异地存储。
- 配置域名、ICP 备案和 HTTPS。
- 将 SSH 22 端口来源限制为固定运维 IP。
- 接入日志、CPU、内存、磁盘和容器重启告警。
- 将服务器升级到至少 4 核 8 GB；当前 2 GB 配置只适合演示。
- 更大流量时将 MySQL、向量库和对象存储迁移到托管服务。
- 多机部署时使用 Redis/API Gateway 实现统一限流，并增加负载均衡和滚动发布。

## 13.1 Chat 附件上传与文档解析链路

Chat 回形针用于“当前会话临时分析”，完整链路如下：

```text
浏览器选择文件
  -> POST /uploads 上传到私有 OSS
  -> 返回 object_key 和短期签名 URL
  -> 用户点击发送
  -> POST /agent/files/analyze 再提交原文件、提示词、session_id、object_key
  -> FastAPI 校验并解析/OCR
  -> 将提取文本和用户要求交给模型
  -> 通过 SSE 返回 session / attachment / delta / done
  -> 保存用户消息、模型回答和附件元数据
```

前端先上传 OSS，是为了让聊天历史能够长期保留附件；发送分析请求时仍携带原始文件，让 API 直接解析，避免再从 OSS 下载一次。后端同时检查 `object_key` 是否属于当前用户，防止跨用户引用附件。

解析由 [file_parser.py](../app/file_parser.py) 完成，不是直接把所有原始文档交给大模型：

| 文件格式 | 当前处理方式 |
| --- | --- |
| TXT、Markdown、CSV | 优先 UTF-8（含 BOM），兼容 GB18030 解码 |
| PDF | `pypdf` 提取前 100 页的文本层；加密 PDF 拒绝处理 |
| DOCX | 读取 OpenXML 的段落/表格文本节点 |
| PNG、JPG、WEBP | Pillow 校正方向和压缩；Tesseract 执行中英文 OCR |
| 图片语义理解 | 开启视觉模型时，同时把压缩后的图片交给视觉模型 |

安全和资源限制：单文件最大 10 MB、图片最大 2500 万像素、视觉图片最长边压缩到 1568 像素、提取文本最多 60000 字符。解析结果会记录提取方式、字符数和是否截断，但完整文档正文不会重复写入聊天消息表。

当前扫描版 PDF 没有文字层时可能提取不到正文，因为尚未实现“PDF 逐页转图片再 OCR”；复杂表格、公式和版式也可能丢失。这是现阶段文档解析能力的主要边界。

Chat 附件默认不会进入 Qdrant。它只用于本次会话分析，避免临时合同、截图或敏感文件未经确认就污染长期知识库。

## 13.2 知识笔记导入与向量化链路

知识笔记页的“导入文档”支持 TXT、Markdown、CSV、PDF、DOCX 和常见图片，单文件最大 10 MB：

1. FastAPI 校验文件名、格式、大小和内容。
2. 文本文件直接解码，PDF/DOCX 提取正文，图片执行 OCR。
3. 提取结果写入 MySQL，成为一条普通知识笔记。
4. 同一事务写入知识索引 Outbox 任务，避免“笔记成功但索引任务丢失”。
5. `knowledge-worker` 异步领取任务，把内容按 500 字、重叠 80 字切块。
6. FastEmbed 使用本地 `bge-small-zh-v1.5` 生成向量，写入 Qdrant。
7. Chat 提问时生成查询向量，按用户 ID 过滤并应用 0.55 相关度阈值，只引用真实命中的笔记。

如果希望文档成为长期知识，必须在“知识笔记”页点击“导入文档”。附件存储支持 `oss`、`local` 和 `auto`：当前线上明确使用 `oss`；`auto` 会在凭证不完整时回退到 Docker `upload_data` 持久卷。本地附件同样通过 HMAC 过期签名 URL 访问，不直接暴露真实磁盘路径。首次创建本地数据卷后需确认容器用户可写：

```bash
sudo docker compose --env-file .env.production exec -u root api \
  sh -c 'mkdir -p /data/uploads && chown -R 10001:10001 /data/uploads'
```

## 13.3 日志与排障

API、模型调用、向量检索和索引 Worker 统一输出 JSON 到标准输出，关键字段包括 `request_id`、事件名、耗时、用户/会话/笔记 ID、模型 TTFT、Token 用量、检索命中数和最高分。日志不会记录密码、Token、完整问题或文档正文。

```bash
cd /opt/fieldnote/python-agent-demo
sudo docker compose --env-file .env.production logs -f --tail=200 api
sudo docker compose --env-file .env.production logs -f --tail=200 knowledge-worker
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

Docker `json-file` 已设置每个文件最大 10 MB、保留 5 个，避免日志无限占满磁盘。单机当前仍未接入腾讯云 CLS/Sentry 和自动告警；正式业务应将 JSON 日志采集到集中平台，并对 5xx、模型失败、索引最终失败和磁盘水位设置告警。

## 13.4 性能、RAG 评测与灾备证据

项目提供 `deploy/load_test.py`、`deploy/rag_eval.py`、`deploy/backup.sh`、`deploy/verify_backup.sh` 和 `deploy/ops_check.sh`。腾讯云实测结果及边界见 [evidence/README.md](evidence/README.md)。

- 本机 FastAPI `/health`：1000 请求、10 并发、0 错误，524.6 RPS，P95 22.5 ms，P99 37.5 ms。
- RAG 小型标注集：阈值 0.55 时 Recall@3 0.75、MRR 0.9375、无答案误引用率 0。
- MySQL dump、Qdrant snapshot、SHA-256/gzip 校验已在服务器执行成功。
- 运行检查覆盖 `/ready`、容器状态、索引失败/积压任务和磁盘使用率。

systemd timer 每天执行备份、每 5 分钟执行运行检查。需要强调：健康接口压测不是 Chat 容量，10 问离线集合不是线上准确率，文件校验也不是隔离环境完整恢复；资深工程师应主动说明证据适用范围。

## 14. 面试讲解版本

### 30 秒版本

> 我把一个 FastAPI + React 的个人知识库 Agent 部署到了腾讯云。前端由 Nginx 托管，`/api` 反向代理到只监听本机端口的 FastAPI；后端通过 Docker Compose 编排 MySQL、Qdrant、Alembic 迁移、API 和知识索引 Worker。上线过程中还处理了国内服务器访问 Docker Hub、PyPI 和 Hugging Face 不稳定的问题，把依赖源切到腾讯镜像，并把中文 Embedding 模型固化到镜像、运行时直接读取本地路径。最后通过 `/ready`、容器状态和真实流式模型请求完成验收。

### 2 分钟展开顺序

1. **先讲入口**：公网只开放 Nginx，前端静态文件和 API 共用一个域名，避免跨域。
2. **再讲容器编排**：MySQL 健康后执行 Alembic，迁移成功才启动 API 和 Worker。
3. **讲数据职责**：MySQL 保存业务数据，Qdrant 保存向量，Worker 通过 Outbox 异步同步索引。
4. **讲流式回答**：浏览器通过 POST + Fetch 读取 SSE，Nginx 关闭缓冲保证增量返回。
5. **讲安全**：密钥只在服务器 `.env.production`，数据库和向量库不暴露公网，API 使用非 root 用户。
6. **讲故障处理**：通过访问日志确认请求到达，再从 API 日志定位到 Embedding 联网加载，最后用本地模型路径把首次检索从分钟级降到秒级。
7. **讲边界**：这是单机生产基线，不是高可用系统；下一步是 HTTPS、自动备份、监控和托管数据库。

### 常见追问

**为什么需要 Nginx？**  
它统一承载静态文件和 API 入口，负责反向代理、上传大小、SSE 超时、安全响应头，后续也方便配置 HTTPS。

**为什么数据库迁移要单独作为任务？**  
避免多个 API Worker 同时执行迁移；只有迁移成功，API 才启动，可以降低版本不一致风险。

**为什么 MySQL 和 Qdrant 都需要？**  
MySQL 负责用户、权限、笔记和会话等强一致业务数据；Qdrant 专门负责高维向量相似度检索和用户过滤。

**为什么聊天会一直 loading？**  
请求实际已进入 FastAPI，但 RAG 在模型生成前要先做 Embedding。运行时错误访问 Hugging Face，导致首段 SSE 长时间不返回。改成明确的本地模型路径后解决。

**当前方案最大的风险是什么？**  
单机和 2 GB 内存。机器故障会整体不可用，内存也限制并发；正式环境应升级配置并引入备份、告警和托管组件。
