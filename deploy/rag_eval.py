"""Offline embedding retrieval evaluation with Recall@K, MRR and false-citation rate."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding


CORPUS = [
    ("python", "Python 基础包括变量、条件判断、循环、函数、列表和字典。"),
    ("fastapi", "FastAPI 使用 Pydantic 校验参数，通过依赖注入管理数据库会话。"),
    ("qdrant", "Qdrant 是向量数据库，支持余弦相似度搜索和 payload 条件过滤。"),
    ("outbox", "事务 Outbox 将业务数据和待处理事件写在同一数据库事务中。"),
    ("sse", "SSE 适合服务端向浏览器单向推送文本增量，响应类型是 text/event-stream。"),
    ("docker", "Docker Compose 可以编排 API、MySQL、Qdrant 和后台 Worker。"),
    ("oss", "私有 OSS 对象通过短期签名 URL 访问，AccessKey 只保存在服务端。"),
    ("mysql", "MySQL 保存用户、笔记、会话和索引任务等强一致业务数据。"),
]
QUERIES = [
    ("Python 怎么写循环和函数？", "python"),
    ("FastAPI 的参数校验用什么？", "fastapi"),
    ("哪个组件负责向量相似度检索？", "qdrant"),
    ("如何保证业务写入和异步事件不丢失？", "outbox"),
    ("为什么聊天流式输出选择 SSE？", "sse"),
    ("容器服务如何统一编排？", "docker"),
    ("私有云附件怎样安全预览？", "oss"),
    ("用户和会话数据保存在哪里？", "mysql"),
    ("今天北京天气如何？", None),
    ("篮球比赛谁赢了？", None),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--threshold", type=float, default=.55)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dataset", type=Path, help="JSONL: {id,text} corpus lines and {query,relevant_ids,should_abstain} query lines")
    args = parser.parse_args()
    options = {"model_name": args.model, "local_files_only": bool(args.model_path)}
    if args.model_path:
        options["specific_model_path"] = args.model_path
    corpus = CORPUS
    queries = QUERIES
    if args.dataset:
        rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
        corpus = [(str(row["id"]), str(row["text"])) for row in rows if row.get("type", "corpus") == "corpus"]
        queries = [(str(row["query"]), row.get("relevant_ids", row.get("expected"))) for row in rows if row.get("type") == "query"]
        if not corpus or not queries:
            raise SystemExit("dataset 至少需要 corpus 行和 query 行")
    model = TextEmbedding(**options)
    corpus_vectors = np.asarray([v for v in model.embed([text for _, text in corpus])])
    query_vectors = np.asarray([v for v in model.embed([query for query, _ in queries])])
    scores = query_vectors @ corpus_vectors.T
    relevant = [(i, expected) for i, (_, expected) in enumerate(queries) if expected]
    unrelated = [(i, expected) for i, (_, expected) in enumerate(queries) if not expected]
    recalls = 0
    reciprocal_ranks = []
    details = []
    for i, expected in relevant:
        ranking = np.argsort(scores[i])[::-1]
        accepted = [j for j in ranking[:args.top_k] if scores[i, j] >= args.threshold]
        ids = [corpus[j][0] for j in accepted]
        expected_ids = expected if isinstance(expected, list) else [expected]
        recalls += int(any(item in ids for item in expected_ids))
        rank = next((rank for rank, j in enumerate(ranking, 1) if corpus[j][0] in expected_ids), 0)
        reciprocal_ranks.append(1 / rank if rank else 0)
        precision = sum(item in expected_ids for item in ids) / args.top_k
        details.append({"query": queries[i][0], "expected": expected_ids, "returned": ids,
                        "precision_at_k": round(precision, 4),
                        "top_score": round(float(scores[i, ranking[0]]), 4)})
    false_citations = sum(
        int(float(scores[i].max()) >= args.threshold) for i, _ in unrelated
    )
    report = {
        "timestamp": datetime.now(UTC).isoformat(), "model": args.model,
        "threshold": args.threshold, "top_k": args.top_k,
        "query_count": len(QUERIES),
        "recall_at_k": round(recalls / len(relevant), 4),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
        "precision_at_k": round(sum(item["precision_at_k"] for item in details) / len(details), 4),
        "false_citation_rate": round(false_citations / len(unrelated), 4),
        "details": details,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
