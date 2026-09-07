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
from collections import Counter
from dataclasses import dataclass
from typing import Protocol


VECTOR_DIMENSIONS = 256
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

# 这些是问法噪声，不是知识主题。若把“下、介绍、怎么”拆成单字或二元组送入
# BM25，长文档会因为偶然出现这些字而获得虚假的高词法分。
_QUERY_FILLERS = (
    "请帮我", "帮我", "请问", "麻烦", "介绍一下", "介绍下", "介绍",
    "讲一下", "讲讲", "说一下", "说说", "解释一下", "解释",
    "是什么", "有哪些", "怎么", "如何", "一下",
)
_TECH_ENTITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "vue": re.compile(r"(?<![a-z0-9])vue(?:\.js)?[23]?(?![a-z0-9])", re.I),
    "react": re.compile(r"(?<![a-z0-9])react(?:\.js)?(?:1[6-9])?(?![a-z0-9])", re.I),
    "angular": re.compile(r"(?<![a-z0-9])angular(?:js)?(?![a-z0-9])", re.I),
    "svelte": re.compile(r"(?<![a-z0-9])svelte(?:kit)?(?![a-z0-9])", re.I),
    "next": re.compile(r"(?<![a-z0-9])next(?:\.js)?(?![a-z0-9])", re.I),
    "nuxt": re.compile(r"(?<![a-z0-9])nuxt(?:\.js)?(?![a-z0-9])", re.I),
    "python": re.compile(r"(?<![a-z0-9])python(?:3)?(?![a-z0-9])", re.I),
    "javascript": re.compile(r"(?<![a-z0-9])(?:javascript|js)(?![a-z0-9])", re.I),
    "typescript": re.compile(r"(?<![a-z0-9])(?:typescript|ts)(?![a-z0-9])", re.I),
    "fastapi": re.compile(r"(?<![a-z0-9])fastapi(?![a-z0-9])", re.I),
    "django": re.compile(r"(?<![a-z0-9])django(?![a-z0-9])", re.I),
    "node": re.compile(r"(?<![a-z0-9])node(?:\.js)?(?![a-z0-9])", re.I),
    "vite": re.compile(r"(?<![a-z0-9])vite(?![a-z0-9])", re.I),
    "webpack": re.compile(r"(?<![a-z0-9])webpack(?![a-z0-9])", re.I),
    "electron": re.compile(r"(?<![a-z0-9])electron(?![a-z0-9])", re.I),
}


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
            # The local hash vector is only a development fallback. Hash collisions
            # are not semantic evidence, so never cite a note with zero lexical overlap.
            if keyword_score <= 0:
                continue
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
    """兼容中英文技术语料的轻量分词，过滤问法噪声且不保留中文单字。"""
    lowered = text.lower()
    for filler in _QUERY_FILLERS:
        lowered = lowered.replace(filler, " ")

    tokens = re.findall(r"[a-z][a-z0-9_.+#-]*|[0-9]+", lowered)
    # Vue3 / Vue 3 都补充 vue 词项，兼容常见技术名的连写与分写。
    for token in list(tokens):
        family = re.fullmatch(r"(vue|react)(?:\.js)?(?:[0-9]+)?", token)
        if family and family.group(1) != token:
            tokens.append(family.group(1))

    for span in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(span) == 1:
            tokens.append(span)
            continue
        # 二/三字窗口兼顾中文召回率；不再保留单字，避免“下、有、的”等碰撞。
        tokens.extend(span[index:index + 2] for index in range(len(span) - 1))
        if len(span) >= 3:
            tokens.extend(span[index:index + 3] for index in range(len(span) - 2))
        if len(span) <= 8:
            tokens.append(span)
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


def keyword_score(query: str, document: str) -> float:
    """Public lexical score used to rerank vector candidates."""
    return _keyword_overlap(_tokenize(query), _tokenize(document))


def entity_compatible(query: str, document: str) -> bool:
    """阻止同领域但对象冲突的技术框架被当作答案证据。

    例如询问 Vue 时，只有 React 且完全未出现 Vue 的笔记可用于候选诊断，
    但不能进入引用；同时包含 Vue/React 的对比资料仍然允许通过。
    """
    query_entities = {
        name for name, pattern in _TECH_ENTITY_PATTERNS.items() if pattern.search(query)
    }
    if not query_entities:
        return True
    document_entities = {
        name for name, pattern in _TECH_ENTITY_PATTERNS.items() if pattern.search(document)
    }
    # 明确点名技术对象时宁可不引用，也不允许一条未出现该对象的内容仅凭
    # 高 Dense 分通过；标题也包含在 document 中，因此正常专题笔记不会受影响。
    return bool(query_entities & document_entities)


def bm25_scores(query: str, documents: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """计算轻量 BM25 稀疏检索分数。

    不依赖外部搜索引擎，便于本地运行；生产规模扩大后可替换为 Elasticsearch/
    OpenSearch 的倒排索引，Pipeline 接口保持不变。
    """
    if not documents:
        return []
    query_terms = list(dict.fromkeys(_tokenize(query)))
    tokenized = [_tokenize(document) for document in documents]
    average_length = sum(len(tokens) for tokens in tokenized) / max(len(tokenized), 1)
    scores = [0.0] * len(documents)
    for term in query_terms:
        document_frequency = sum(term in tokens for tokens in tokenized)
        inverse_frequency = math.log(1 + (len(documents) - document_frequency + 0.5) / (document_frequency + 0.5))
        for index, tokens in enumerate(tokenized):
            frequency = Counter(tokens)[term]
            if not frequency:
                continue
            length_normalizer = 1 - b + b * len(tokens) / max(average_length, 1)
            scores[index] += inverse_frequency * (frequency * (k1 + 1)) / (frequency + k1 * length_normalizer)
    return scores
