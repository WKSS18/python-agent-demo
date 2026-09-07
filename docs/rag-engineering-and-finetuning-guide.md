# RAG 检索工程、向量数据库与模型微调业务方案

本文既是 `python-agent-demo` 的实现说明，也是面试讲解与后续学习路线。核心原则是：

- 实时、私有、经常变化的事实放在 RAG，不写进模型参数。
- 稳定的行为、语气、格式和任务模式可以通过提示词或微调改善。
- 检索结果必须经过权限过滤、二阶段排序和置信度门控，低置信度时宁可不引用。

## 1. 向量数据库如何选择

| 方案 | 适用场景 | 优点 | 主要代价 | 本项目建议 |
|---|---|---|---|---|
| Qdrant | 中小型知识库、多租户 SaaS、独立扩容 | API 简洁、payload filter 强、部署轻、HNSW 成熟 | 多一个基础设施组件 | 当前生产默认，最符合项目规模 |
| pgvector | 已重度使用 PostgreSQL、数据量中小、强事务需求 | 关系数据与向量同库、事务一致性好 | 大规模向量检索与业务 SQL 争抢资源 | PostgreSQL 技术栈项目优先考虑 |
| Milvus | 亿级向量、高吞吐、多索引/集群 | 大规模能力强、索引选择丰富 | 运维和资源成本高 | 只有容量和吞吐证明 Qdrant 不够时采用 |
| Elasticsearch/OpenSearch | 关键词检索、过滤、日志搜索本来就是核心 | BM25、倒排、向量和复杂过滤一体 | 集群内存和运维成本较高 | 商品搜索、法规搜索等词法需求强的业务 |
| 托管向量服务 | 团队小、需要快速上线和跨地域 | 免运维、弹性扩缩 | 成本、数据合规和供应商锁定 | 有明确 SLA/合规预算时选择 |

选择不是看“谁最先进”，而是按五个维度评估：向量规模与 QPS、过滤复杂度、事务一致性、团队运维能力、数据合规与预算。

本项目使用 `VectorBackend` 协议隔离业务层，当前工厂注册 Qdrant。MySQL 始终是事实源，Qdrant 是可重建索引；Outbox 保证笔记写成功后索引任务不会丢。

## 2. 稠密向量和稀疏向量底层原理

### 2.1 稠密向量 Dense Retrieval

Embedding 模型把文本映射成固定维度浮点向量。语义相近的文本在向量空间方向相近，通常使用余弦相似度：

```text
cos(q, d) = (q · d) / (||q|| × ||d||)
```

Qdrant 使用 HNSW 近似最近邻索引，避免每次查询遍历所有向量。稠密检索擅长同义表达，例如“怎么退钱”和“退款流程”，但可能忽略精确型号、人名、错误码和罕见术语。

### 2.2 稀疏检索 Sparse Retrieval

稀疏向量的维度对应词项，大部分维度为零。BM25 根据词频、逆文档频率和文档长度计算相关性：

```text
BM25(q,d) = Σ IDF(term) × TF饱和项 × 文档长度归一化
```

它擅长精确关键词、编号、专有名词，但不理解“退钱”和“退款”可能是同一语义。项目在本地实现 BM25；规模扩大后可把稀疏召回替换为 Elasticsearch/OpenSearch。

### 2.3 混合召回与 RRF

项目并行执行：

```text
问题
 ├─ FastEmbed -> Qdrant dense Top-N
 └─ 分词/BM25 -> sparse Top-N
          ↓
Reciprocal Rank Fusion（RRF）
          ↓
Reranker 二次排序
```

Dense 和 BM25 的原始分数不在同一量纲，直接相加容易受模型或语料变化影响。RRF 使用名次融合：

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

因此无需假设两路分数可直接比较。融合后仍保留 dense、sparse、title match 等特征用于第二阶段排序。

## 3. 如何保证检索准确性

准确性不是单个 Top-K 参数，而是一条质量链：

1. 数据质量：去除导航、页眉页脚、重复段落，记录文档版本和更新时间。
2. 结构化切块：优先按 Markdown 标题/段落切分，再按 token 预算截断，并保留标题和父级路径。
3. 多租户过滤：向量查询强制 `owner_id` filter，召回后再回 MySQL 校验归属。
4. 混合召回：语义召回解决同义表达，BM25 解决精确词和编号。
5. Rerank：只对少量候选做更昂贵的相关性判断。
6. 去重：同一笔记只保留最佳分块，避免重复上下文挤占 token。
7. 置信度门控：结合首位分数、dense/sparse 证据和首二名差距判断是否引用。
8. 生成约束：Prompt 明确只能引用提供的 notes，并把知识文本视为不可信数据。
9. 可观测与评测：记录候选、分数、拒绝原因；离线评估 Recall@K、MRR、nDCG 和无答案误引用率。

### 错误结果如何处理

| 错误类型 | 检测 | 处理 |
|---|---|---|
| 完全无命中 | 无 dense/sparse 候选 | 不返回引用；提示模型使用通用知识并声明没有知识库依据 |
| 弱相关误命中 | top/rerank/confidence 低 | 置信度门控拒绝，不把候选放进 Prompt |
| 多个候选接近 | Top1-Top2 margin 很小 | 标记 ambiguous；要求用户补充条件或降低自动决策权限 |
| 引用正确但答案错误 | Faithfulness 低、引用不支持结论 | 强化引用约束、答案后校验、人工反馈进入评测集 |
| 索引过期 | MySQL 版本高于索引任务 | Outbox 重试、任务告警、reindex；查询失败降级 BM25 |
| 提示注入 | 文档出现“忽略规则”等文本 | 系统提示声明文档不可信，Hook 可增加内容清洗和风险标记 |

高风险业务（医疗、法律、财务审批）应采用“低置信度拒答 + 人工复核”；低风险知识助手可以降级为模型通用知识，但必须区分是否有企业知识库依据。

## 4. Rerank 方案

项目支持三种模式：

- `off`：只使用融合排序，速度最快，适合本地演示。
- `hybrid`：默认模式，使用 dense、BM25、RRF、正文词项和标题词项加权，无额外模型下载。
- `cross_encoder`：将 `query + candidate` 同时输入交叉编码器，直接输出相关性；精度通常更高，但延迟和算力开销更大。

典型生产参数：先召回 20～100 个候选，Rerank 后保留 3～8 个。不要让 Cross Encoder 扫描全库，它是二阶段排序器，不是向量数据库替代品。

## 5. RAG Hook 是什么

RAG Hook 是检索生命周期中的受控扩展点，不是某个固定框架。当前生命周期：

```text
before_retrieve
  -> dense + sparse retrieve
after_retrieve
  -> rerank
after_rerank
  -> confidence evaluate
on_low_confidence
```

项目内置：

- `normalize_query`：规范空白并删除无信息口语前缀。
- `deduplicate`：同一 Note 只保留最佳分块。
- `confidence_guard`：记录拒绝原因，形成评测和告警闭环。

业务扩展示例：

- 客服：在 `before_retrieve` 注入产品型号、地区和会员等级过滤。
- 法务：在 `after_retrieve` 过滤已废止法规，并优先最新生效版本。
- 电商：加入库存、价格、上架状态等实时 metadata filter。
- 企业权限：按部门、项目、密级增加 ACL Hook；绝不能只在 Prompt 中声明权限。
- 质量闭环：`on_low_confidence` 记录待标注问题，进入人工补充知识流程。

Hook 使用固定注册表，不允许通过环境变量任意动态导入 Python 路径，避免生产配置变成代码执行入口。

## 6. RAG、提示词工程与微调如何选择

| 需求 | 首选 | 原因 |
|---|---|---|
| 回答使用最新制度、商品、合同、个人笔记 | RAG | 知识变化快，可追溯、可删除、可做权限隔离 |
| 固定语气、JSON 格式、少量行为约束 | 提示词工程 | 成本最低、迭代最快 |
| 大量稳定任务模式、行业表达、工具调用习惯 | LoRA/QLoRA 微调 | 将重复行为固化到参数，减少长 Prompt |
| 最新知识 + 稳定行业回答风格 | RAG + 微调 | RAG 提供事实，微调负责行为和格式 |
| 模型不会某种复杂推理/分类任务 | 先做数据与评测，再考虑微调 | RAG 只能提供知识，不能自动获得新的任务能力 |

### 微调落地流程

1. 定义任务和基线：先用 Prompt + RAG 得到可比较的基线。
2. 构建数据：收集高质量 instruction/input/output、工具调用轨迹和拒答案例。
3. 数据治理：去重、脱敏、划分 train/validation/test，禁止把测试集混入训练。
4. 训练：优先 LoRA/QLoRA；记录基础模型、模板、超参数、数据版本和随机种子。
5. 评估：任务准确率、格式遵循率、幻觉率、安全拒答率、RAG Faithfulness 和延迟成本。
6. 灰度：影子流量或小比例 A/B，保留基础模型回滚能力。
7. 持续迭代：线上差评进入候选数据，必须人工审核后才能加入下一版训练集。

项目配置 `RAG_FINE_TUNED_MODEL_ENABLED` 和 `RAG_FINE_TUNED_MODEL`。只有检索通过置信度门控且存在可靠 notes 时才路由到微调回答模型；无可靠上下文时仍走基础模型，防止把微调模型误当知识库。

## 7. 业务场景方案

### 企业客服知识助手

- 数据：产品手册、FAQ、售后政策、工单解决方案。
- 检索：产品型号和地区 metadata filter + dense/BM25 + Cross Encoder。
- 错误处理：退款、赔付等动作低置信度必须转人工。
- 微调：训练标准客服语气、结构化工单摘要和工具调用格式，不训练实时政策正文。

### 法规/合同检索

- 数据：带生效时间、失效时间、地区和版本的法规条款。
- Hook：查询时注入日期与辖区；过滤失效版本；结果强制显示出处。
- 指标：条款 Recall@K、引用准确率、无答案误引用率优先于回答流畅度。
- 微调：可以训练条款分类和风险标签，最终意见必须保留人工审核。

### 电商商品与销售助手

- 数据：商品说明进入向量库；价格、库存走实时数据库/API。
- 混合检索：Dense 找需求相似商品，Sparse 找精确型号和 SKU。
- Hook：库存、地区可售、价格区间过滤；Rerank 加入业务相关性但不能绕过用户意图。
- 微调：训练导购话术和结构化推荐理由，不把动态库存微调进模型。

### 个人/团队知识库（本项目）

- MySQL 保存 Note 与权限，Qdrant 保存可重建 chunk 向量。
- 用户问题经过混合召回和 Rerank；低置信度不引用笔记。
- `/knowledge/search/diagnostics` 返回可解释分数，支持面试演示、阈值调优和问题定位。
- 笔记更新通过事务 Outbox 异步重建索引，Qdrant 故障时降级到本地检索。

## 8. 配置与诊断接口

关键配置见 `.env.example`：

```env
VECTOR_STORE_PROVIDER=qdrant
RAG_RERANKER=hybrid
RAG_RERANKER_TOP_N=5
RAG_MIN_CONFIDENCE=0.42
RAG_MIN_TOP_SCORE=0.45
RAG_MIN_SCORE_MARGIN=0.02
RAG_HOOKS=normalize_query,deduplicate,confidence_guard
RAG_FINE_TUNED_MODEL_ENABLED=false
RAG_FINE_TUNED_MODEL=
```

登录后诊断检索：

```bash
curl -X POST http://127.0.0.1:8000/knowledge/search/diagnostics \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"退款审批流程是什么"}'
```

响应包含 `dense_score`、`sparse_score`、`fusion_score`、`rerank_score`、整体 `confidence` 和拒绝 `reason`。这些字段应进入离线标注和线上监控，而不是凭感觉调阈值。
