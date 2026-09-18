# Fieldnote AI Agent：真实业务版项目说明

## 一、项目定位

这是一个面向个人/团队知识库的 AI Agent：用户上传或创建知识笔记，系统异步解析文档、切块、生成真实语义向量并持久化到 Qdrant；聊天时只在当前用户租户范围内召回相关证据，再由兼容 Anthropic Messages 的大模型生成回答，并通过 SSE 流式返回。

核心业务不是“把文本拼给模型”，而是：

```text
上传文件 -> OSS/本地对象存储 -> MySQL 导入任务
         -> Outbox Publisher -> RabbitMQ
         -> Document Worker 解析/OCR -> Note + 向量 Outbox
         -> Knowledge Worker -> FastEmbed -> Qdrant
用户提问 -> 用户隔离的 Dense + BM25 -> RRF -> Rerank -> 置信度门控
         -> LLM 流式回答 -> 持久化消息与真实引用快照
```

## 二、哪些地方已经是真实实现

| 能力 | 实现 | 业务价值 |
|---|---|---|
| 文档解析 | PDF、DOCX、TXT、Markdown、CSV、图片 OCR/视觉预处理 | 不依赖手工录入 |
| 文档切片 | 标题/段落优先，超长段落使用带 overlap 的窗口切分 | 降低跨段落截断和上下文碎片 |
| Embedding | FastEmbed 本地模型 `BAAI/bge-small-zh-v1.5` | 真实中文语义向量，不是字符串相似度 |
| 向量库 | Qdrant 持久化、Cosine Top-K、payload filter | 支持重启恢复和租户隔离 |
| 稀疏召回 | BM25/词法覆盖 | 技术名、错误码、专有名词召回更稳 |
| 混合排序 | Dense + Sparse + RRF + 可选 Cross-Encoder | 兼顾语义和精确匹配 |
| 可信引用 | 绝对分数、词法/语义门槛、margin、source trust | 低置信度时 abstain，减少误引用 |
| 异步索引 | MySQL 事务 Outbox + RabbitMQ + 独立 Worker + 重试/死信 | API 不被 embedding/OCR 阻塞，任务不丢 |
| 生成 | Anthropic Messages 兼容协议，SSE 增量输出 | 首 token 快，前端可实时展示 |
| 数据与安全 | MySQL、JWT、owner_id 过滤、OSS 私有对象/签名 URL | 多用户数据隔离和最小暴露 |

## 三、文档切片的真实业务规则

`app/vector_store.py::split_note` 不再是单纯的固定字符截断：

1. 规范化换行，按空行拆成段落。
2. Markdown 标题或中文“第 X 章/节”作为语义边界。
3. 短段落合并到约 700 字的 chunk，减少碎片。
4. 超长段落按 700 字窗口、120 字 overlap 切分。
5. 每个 chunk 追加文档标题，并作为 Qdrant payload 保存 `owner_id`、`note_id`、`chunk_index`、`title` 和正文。

面试时可以解释：chunk 过大增加 token 成本且召回不精确，过小会丢失上下文；overlap 用来覆盖跨边界语义。真实项目还会用离线标注集调优 chunk size、Top-K 和阈值。

## 四、一次完整请求如何走

### 1. 导入

API 先把文件保存到对象存储，并在 MySQL 写入 `document_import_jobs`。事务提交后，publisher 才把任务投递到 RabbitMQ；消费者手动 ACK，失败指数退避，超过次数进入死信队列。Document Worker 下载文件，调用解析器/OCR，创建 Note，同时写向量 Outbox。Knowledge Worker 领取 Outbox，幂等地删除旧向量、重新切块、批量 embedding 并 upsert Qdrant。

### 2. 问答

Service 读取当前用户 Notes 快照并调用 Qdrant。Qdrant 查询强制 `owner_id` filter；回表后再校验 note 是否仍属于该用户。RagPipeline 将 dense hits 与 BM25 合并，用 RRF 稳定融合，再进行 hybrid 或 Cross-Encoder rerank。若相关性、词法/语义证据或分数 margin 不足，返回无引用结果，而不是把最不差的候选当答案依据。最终只把证据 chunk、标题和引用快照交给模型。

### 3. 生成与持久化

API 以 SSE 输出 `session`、`thinking`、`sources`、`delta`、`done` 等事件。模型结束后，助手消息和 used_notes 快照在短事务中写入 MySQL，历史记录不依赖 Note 后续修改。

## 五、原先的模拟点与处理方式

- 请求内哈希向量：保留为本地单元测试/离线兜底能力，但生产配置强制 `VECTOR_STORE_ENABLED=true` 且 `ALLOW_LEGACY_RAG_FALLBACK=false`；Qdrant 无结果时直接 abstain，不伪装成真实语义命中。
- 无密钥 mock 回复：仅本地 `ALLOW_MOCK_MODEL=true` 可用；生产环境校验失败或直接抛出模型服务未配置错误。
- 固定字符切片：已改为标题/段落优先 + overlap 窗口。
- Chat 临时附件：仍是“当前会话分析”，不会自动污染知识库；需要进入知识库的文件走异步导入链路，这是有意的业务边界。

## 六、技术难点与亮点

1. **最终一致性**：Note 与 Outbox 在同一 MySQL 事务，队列只负责投递；publisher confirm、手动 ACK、幂等 job 状态和重试避免任务丢失/重复。
2. **多租户隔离**：SQL 查询、Qdrant filter、回表校验三层同时限制 `owner_id`，防止向量库误召回其他用户数据。
3. **RAG 可信度**：不把 Top-K 等同于相关性；保存 dense/sparse/fusion/rerank/evidence 分数和原因，低置信度自动 abstain。
4. **流式事务边界**：模型可能运行数分钟，先结束只读事务；SSE 结束后用短写事务保存消息，避免连接池被长请求占满。
5. **模型适配**：用 Anthropic Messages 兼容接口隔离供应商，可切 DeepSeek/Anthropic；模型 token、TTFT、异常和断连均有结构化日志。
6. **安全与成本**：上传大小/像素/抽取字符限制，图片预处理，私有 OSS 签名 URL，计算器使用受限 AST，不执行任意代码。

## 七、面试高频问题与回答要点

**为什么 MySQL 和 Qdrant 要分开？** MySQL 保存强一致业务实体、用户、会话和任务；Qdrant 专注高维向量 Top-K。两者通过 Outbox 最终一致，避免把向量写入阻塞核心事务。

**如何保证用户 A 看不到用户 B 的笔记？** JWT 得到 owner_id；SQL、Qdrant payload filter、回表归属检查都使用 owner_id，不能只相信前端传参。

**向量索引失败怎么办？** Note 已经落库，Outbox job 保留 pending/failed 状态并重试；可人工 reindex。生产不回退哈希向量，检索无证据就 abstain。

**为什么要 BM25 + 向量？** 向量擅长同义表达，BM25 擅长版本号、类名、错误码和精确术语；RRF 避免不同分数尺度直接相加造成偏差。

**为什么要 rerank？** 召回阶段追求 recall，rerank 阶段用更贵但更准确的模型/特征排序；最终引用还要经过绝对证据和 margin 门禁。

**为什么用 SSE？** 业务是服务端单向增量输出；SSE 比 WebSocket 简单，适合 POST + Authorization 的流式聊天。

**如何处理重复导入和 Worker 崩溃？** job 状态、note_id、幂等索引 job 和确定性 UUID；消息未 ACK 会重投，已完成任务直接返回，不重复创建 Note。

**当前还不应夸大的地方？** 单机部署还不是多 AZ 高可用；缺少集中式 Redis 限流、OpenTelemetry 全链路追踪、大规模标注集和真实 MySQL/Qdrant/OSS 集成压测。这些是明确的下一步，而不是已经完成的能力。

## 八、验证命令

```bash
.venv/Scripts/python -m compileall -q app
.venv/Scripts/python -m unittest discover -s tests -v
docker compose --env-file .env.production config
```

生产环境至少确认：`ALLOW_MOCK_MODEL=false`、`VECTOR_STORE_ENABLED=true`、`ALLOW_LEGACY_RAG_FALLBACK=false`，并检查 Qdrant collection、RabbitMQ 队列和两个 Worker 的健康状态。
