# 个人知识库增强执行归档

## 本次执行目标

按照产品增强顺序推进：智能笔记复盘、RAG 批量评测、分类型文档切片、WebRTC/Electron/RN 方案归档。

## 已完成

- 生产 RAG 已启用真实 FastEmbed + Qdrant，禁止生产 mock 模型和请求内哈希向量降级。
- 文档切片已改为标题/段落优先、超长段落 overlap 窗口。
- `deploy/rag_eval.py` 支持外部 JSONL 数据集。
- 新增 Recall@K、Precision@K、MRR、误引用率和逐问题明细输出。
- 新增示例评测集：`tests/fixtures/rag_eval.jsonl`。
- 已归档 WebRTC、Electron、React Native 的技术路线和实施顺序。

## 评测集格式

```json
{"type":"corpus","id":"note-1","text":"..."}
{"type":"query","query":"...","relevant_ids":["note-1"]}
```

执行：

```bash
python deploy/rag_eval.py --dataset tests/fixtures/rag_eval.jsonl --top-k 3 --output docs/evidence/rag-eval-custom.json
```

## 下一阶段

1. 增加 `note_reviews` 表和 `/notes/{id}/review` 接口，生成摘要、关键点、自测题和待办。
2. 按 PDF/DOCX/Markdown 保存页码、标题路径和 chunk 元数据。
3. 增加真实 MySQL/Qdrant/OSS 集成评测和答案忠实度人工标注。
4. 第一版语音功能先采用 MediaRecorder 上传转写，再评估 WebRTC 实时语音。

## 真实性边界

当前批量评测已经支持真实 embedding 模型，但示例数据集仍是小规模人工标注集；不能把示例指标当作生产效果承诺。生产上线前需要从真实用户文档抽样、人工标注相关 chunk 和无答案问题，并固定模型版本后持续回归。
