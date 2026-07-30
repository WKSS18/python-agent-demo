"""轻量 RAG 检索工具。

当前项目不引入独立向量库，而是在请求内对当前用户 Notes 构建临时向量索引。
这样能把“切分 -> embedding -> 相似度 -> 混合排序”的核心思路落到代码里，同时
保持 Demo 可本地运行。生产环境应把 embedding 结果持久化到 pgvector、Milvus、
Elasticsearch 或专门的向量服务中。
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol


VECTOR_DIMENSIONS = 256
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


class NoteLike(Protocol):
    """检索只依赖 Note 的最小字段，避免耦合 ORM 或 Pydantic 类型。"""

    id: int
    title: str
    content: str


@dataclass(frozen=True)
class RetrievedNote:
    """RAG 召回结果，保留可解释分数便于调试和面试说明。"""

    note: NoteLike
    score: float
    keyword_score: float
    vector_score: float
    matched_chunk: str


def retrieve_notes(
    question: str,
    notes: list[NoteLike],
    limit: int = 5,
    min_score: float = 0.08,
) -> list[RetrievedNote]:
    """对用户 Notes 做混合检索：关键词匹配 + 本地哈希向量相似度。"""
    query_tokens = _tokenize(question)
    query_vector = _embed(question)
    candidates: dict[int, RetrievedNote] = {}

    for note in notes:
        for chunk in _chunk_note(note):
            vector_score = _cosine_similarity(query_vector, _embed(chunk))
            keyword_score = _keyword_overlap(query_tokens, _tokenize(f"{note.title} {chunk}"))
            # 关键词更精确，向量更擅长语义近似；Demo 中用固定权重表达混合检索思想。
            score = keyword_score * 0.55 + vector_score * 0.45
            if score < min_score:
                continue
            current = candidates.get(note.id)
            if current is None or score > current.score:
                candidates[note.id] = RetrievedNote(
                    note=note,
                    score=score,
                    keyword_score=keyword_score,
                    vector_score=vector_score,
                    matched_chunk=chunk,
                )

    return sorted(candidates.values(), key=lambda item: item.score, reverse=True)[:limit]


def _chunk_note(note: NoteLike) -> list[str]:
    """按字符长度切块；真实项目可按 Markdown 标题、段落和 token 预算切分。"""
    text = f"{note.title}\n{note.content}".strip()
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks: list[str] = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for start in range(0, len(text), step):
        chunk = text[start:start + CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _tokenize(text: str) -> list[str]:
    """兼容中英文的轻量分词：英文按词，中文补充二字窗口。"""
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", lowered)
    chinese_chars = [token for token in tokens if len(token) == 1 and "\u4e00" <= token <= "\u9fff"]
    tokens.extend("".join(pair) for pair in zip(chinese_chars, chinese_chars[1:], strict=False))
    return tokens


def _embed(text: str) -> list[float]:
    """用哈希 trick 生成本地向量，模拟 embedding 的稠密相似度接口。"""
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in _tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % VECTOR_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def _keyword_overlap(query_tokens: list[str], document_tokens: list[str]) -> float:
    if not query_tokens or not document_tokens:
        return 0.0
    query_set = set(query_tokens)
    document_set = set(document_tokens)
    return len(query_set & document_set) / len(query_set)
