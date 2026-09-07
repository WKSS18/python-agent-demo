"""Optional interview notes describing capabilities actually present in this repo."""

from dataclasses import dataclass


SHOWCASE_VERSION = "2026.08.1"
SOURCE_PREFIX = "agent-showcase"


@dataclass(frozen=True)
class ShowcaseNote:
    key: str
    title: str
    body: str
    suggested_question: str

    @property
    def source_key(self) -> str:
        return f"{SOURCE_PREFIX}:{SHOWCASE_VERSION}:{self.key}"

    @property
    def content(self) -> str:
        return self.body.strip()


SHOWCASE_NOTES = (
    ShowcaseNote(
        "architecture",
        "[Agent项目] 架构与请求链路",
        """
## 业务目标
Fieldnote 是个人知识笔记与 AI 对话项目。用户维护私有笔记、上传文档、向 Agent 提问，并查看回答使用的真实引用。

## 已实现链路
React Web 通过 POST + SSE 请求 FastAPI；后端完成 JWT 鉴权和 owner_id 隔离，读取短期会话上下文，发现 MCP 工具，执行混合 RAG，再调用 Anthropic Messages 兼容模型流式生成。回答完成后保存消息、引用快照和执行步骤。

同步接口使用 LangGraph 表达 `retrieve_notes -> generate_answer` 两节点图；流式接口为了控制 SSE 生命周期、短事务和工具事件，在 AgentService 中显式编排。

## 代码证据
- `app/agent.py`：LangGraph、模型适配、工具选择。
- `app/services.py`：会话、RAG、MCP、SSE 和消息事务。
- `src/components/ChatPage.tsx`：AbortController 与流状态隔离。

## 面试边界
当前是单 Agent + 受控工作流，不应声称已经实现 Supervisor 多 Agent。多 Agent State、共享预算和并行聚合属于下一阶段演进。
""",
        "我的 Agent 项目完整请求链路是什么？",
    ),
    ShowcaseNote(
        "rag",
        "[Agent项目] 混合 RAG、Rerank 与置信度门禁",
        """
## 已实现方案
知识笔记写入 MySQL 后，同一事务创建 KnowledgeIndexJob；后台 Worker 将分块 Embedding Upsert 到 Qdrant。查询时 Dense 向量召回与中文 BM25 稀疏召回通过 RRF 融合，再执行 Cross Encoder 或可解释 Hybrid Rerank。

Pipeline 不把 TopK 自动当成答案：它结合 Top1 Rerank、Dense、Sparse 和 Top1/Top2 Margin 计算置信度。低于阈值时不返回引用，避免把“最相似”误认为“足够相关”。

## 可解释性
`POST /knowledge/search/diagnostics` 返回 Dense、Sparse、Fusion、Rerank、置信度和拒答原因，并且仍强制限定当前用户。

## 代码证据
- `app/rag_pipeline.py`：Hook、RRF、Rerank 和门禁。
- `app/vector_backends.py`：Qdrant Provider。
- `app/knowledge_worker.py`：异步索引。
- `deploy/rag_eval.py`：离线检索评测。

## 面试说法
准确率要分层：先看正确 Chunk 是否进入 Recall@K，再看 Rerank、门禁、Context 和生成，不能一看到错误就统一调整向量阈值。
""",
        "我的项目如何保证 RAG 检索准确度？",
    ),
    ShowcaseNote(
        "memory-and-race",
        "[Agent项目] 会话记忆、停止生成与竞态隔离",
        """
## 已实现方案
后端从当前 Session 读取最近消息，去掉本次已保存的用户问题，再把最近 8 条、每条最多 500 字符组织成短期记忆。会话归属通过 owner_id 校验。

前端每次生成创建新的 generation 和 AbortController；切换会话、重新生成或停止时 Abort 旧流。所有 SSE 回调写状态前调用 `isCurrent()`：Abort 负责节约资源，generation 保证旧任务没有资格覆盖当前 UI。

后端只在模型完整生成后保存 Assistant 消息；客户端断开触发 GeneratorExit，不把半截答案当完整历史。数据库查询后先结束只读事务，再等待慢模型，避免长期占用连接池。

## 当前边界
当前记忆是滑动窗口，没有独立长期记忆表、滚动摘要和完整 TokenBudgetManager。面试应说“短期记忆已实现，长期记忆与结构化摘要是演进方案”。
""",
        "我的聊天如何停止生成并避免旧消息覆盖？",
    ),
    ShowcaseNote(
        "mcp-tools",
        "[Agent项目] MCP 工具、天气路由与安全边界",
        """
## 已实现方案
API 通过 Streamable HTTP 从独立 MCP Server 动态发现工具，只允许模型选择 Server 实际提供的白名单。天气属于高确定性意图：问题包含城市时使用显式城市；没有城市时优先使用前端授权经纬度，定位不可用才采用默认城市上海。

工具参数由 MCP Schema 校验；工具结果被视为不可信数据，只能作为回答材料，不能成为系统指令。股票工具只展示信息，不给收益承诺和买卖指令。

## 失败处理
工具不可用时执行步骤显示错误并安全降级；明确是工具意图但缺少参数时，返回确定性的补充提示，不让模型错误声称“没有接入工具”。

## 代码证据
- `app/mcp_server.py`、`app/mcp_client.py`。
- `app/agent.py`：天气路由和模型 Tool Use。
- `app/services.py`：工具步骤与降级。
""",
        "天气工具为什么能自动调用，MCP 安全怎么保证？",
    ),
    ShowcaseNote(
        "document-ingestion",
        "[Agent项目] 文档上传到向量库的可靠链路",
        """
## 已实现链路
上传接口限制文件大小和类型，把原文件保存到私有 OSS/本地对象存储，然后创建 DocumentImportJob。生产由 Publisher 扫描未发布任务并通过 RabbitMQ Publisher Confirm 投递；Worker 执行解析或 OCR，创建 Note 和 KnowledgeIndexJob，最后由 Knowledge Worker 生成 Embedding 并写入 Qdrant。

```text
Upload -> Object Storage -> DocumentImportJob -> RabbitMQ
-> Parse/OCR -> Note + KnowledgeIndexJob -> Embedding -> Qdrant
```

任务暴露 queued、parsing、creating_note、retrying、completed、failed 阶段，前端轮询展示进度。消息只携带 job_id/object_key，不把大文件塞进 RabbitMQ。

## 可靠性
任务状态、尝试次数和错误持久化；临时错误指数退避；Note 与索引 Outbox 在同一事务。Qdrant 使用 Upsert，Worker 可重试。

## 代码证据
- `app/document_publisher.py`、`app/document_worker.py`。
- `app/file_parser.py`、`app/knowledge_worker.py`。
""",
        "上传一份 PDF 后是怎样进入向量库的？",
    ),
    ShowcaseNote(
        "production",
        "[Agent项目] 生产部署、可观测性与故障降级",
        """
## 已实现能力
项目提供 Docker Compose、Nginx SSE 配置、MySQL、RabbitMQ、Qdrant、私有对象存储、健康/就绪探针和 Prometheus 指标。生产配置会校验弱密钥、SQLite、CORS 通配符、模型 Token 和 Qdrant Key，危险配置 Fail Fast。

模型流记录模型名、总耗时、TTFT、Input/Output Token 和结果状态；RAG 记录候选数、置信度与拒答；HTTP 中间件生成 Request ID、指标和限流。向量检索失败会回退本地检索，工具失败会降级，但不会把无可靠证据包装成高置信答案。

数据库事务与慢模型调用分离，避免 SSE 长连接占用数据库连接；文档和向量任务有重试、死信和运维检查脚本。

## 面试说法
生产化不是中间件堆砌，而是成功、超时、断连、重复、限流和部分失败都有明确行为，并能用 Trace 和指标定位故障层。
""",
        "怎么证明这个 Agent 项目不是只会跑的 Demo？",
    ),
    ShowcaseNote(
        "truth-and-roadmap",
        "[Agent项目] 已实现能力与演进路线",
        """
## 已实现
- 单 Agent + LangGraph 两节点同步图、流式受控工作流。
- 私有笔记混合 RAG、Rerank、门禁和引用。
- 最近 8 条消息组成的短期记忆。
- MCP 工具发现、天气/股票/计算工具与安全降级。
- SSE 执行步骤、停止生成和前端竞态隔离。
- 结构化创建笔记表单及重复提交幂等。
- 文档异步导入、RabbitMQ、Outbox、Qdrant。
- 可选微调模型路由；动态事实仍由 RAG 提供。

## 演进中，不应冒充已上线
- Supervisor + 多专业 Agent 并行编排。
- 请求级精确 Token Budget、长期记忆和滚动摘要。
- 多供应商 Model Gateway、熔断和稳定流量分桶。
- 完整 LoRA/QLoRA 训练流水线；当前仓库只有微调接入边界与方案。
- 自动化 LLM Judge 与全量线上 A/B 平台。

## 推荐面试表达
先演示已实现的检索、引用、工具、短期记忆、停止生成和文档入库；再说明为什么下一阶段增加 Token 压缩、长期记忆、多 Agent 和 Model Gateway。把演进方案说成设计判断，而不是虚构经历。
""",
        "这个 Agent 项目哪些已经实现，哪些还是演进方案？",
    ),
)
