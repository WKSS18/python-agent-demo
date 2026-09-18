"""Qdrant 向量知识库适配层。

笔记按重叠窗口切块，FastEmbed 在本地生成真实语义向量，Qdrant 负责持久化、
用户过滤和 Top-K 召回。该模块不依赖 ORM，便于独立测试和替换向量供应商。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import re
import time
from typing import Iterable
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.config import get_settings


logger = logging.getLogger(__name__)


CHUNK_SIZE = 700
CHUNK_OVERLAP = 120
_PREPARED_COLLECTIONS: set[tuple[str, str]] = set()


@dataclass(frozen=True)
class VectorHit:
    note_id: int
    chunk: str
    score: float


def split_note(title: str, content: str) -> list[str]:
    """按标题/段落优先、窗口兜底切块，保留 overlap 和章节上下文。

    真实知识库不能只按固定字符截断：Markdown 标题、段落和列表是天然语义边界。
    这里先按空行/标题聚合，再对超长段落做重叠窗口切分，最终每块都带文档标题。
    """
    body = content.replace("\r\n", "\n").strip()
    if not body:
        return [title.strip()]
    sections = [part.strip() for part in re.split(r"\n\s*\n+", body) if part.strip()]
    units: list[str] = []
    current = ""
    for section in sections:
        # 标题开启新语义段；短段落尽量合并以减少碎片。
        is_heading = bool(re.match(r"^(#{1,6}\s+|第[一二三四五六七八九十0-9]+[章节部分])", section))
        if current and (is_heading or len(current) + len(section) + 2 > CHUNK_SIZE):
            units.append(current)
            current = ""
        current = f"{current}\n\n{section}".strip()
    if current:
        units.append(current)

    chunks: list[str] = []
    previous_tail = ""
    for unit in units:
        if len(unit) <= CHUNK_SIZE:
            chunk = f"{previous_tail}\n{unit}".strip() if previous_tail else unit
            chunks.append(chunk)
            previous_tail = unit[-CHUNK_OVERLAP:]
            continue
        step = CHUNK_SIZE - CHUNK_OVERLAP
        for start in range(0, len(unit), step):
            part = unit[start:start + CHUNK_SIZE].strip()
            if part:
                chunk = f"{previous_tail}\n{part}".strip() if previous_tail and start == 0 else part
                chunks.append(chunk)
                previous_tail = part[-CHUNK_OVERLAP:]
    return [f"{title.strip()}\n{chunk}".strip() for chunk in chunks if chunk]


class VectorStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.url = settings.qdrant_url.rstrip("/")
        self.collection = settings.qdrant_collection
        self.timeout = settings.vector_request_timeout_seconds
        self.api_key = settings.qdrant_api_key
        self.score_threshold = settings.rag_vector_score_threshold

    def index_note(self, owner_id: int, note_id: int, title: str, content: str) -> int:
        started = time.perf_counter()
        chunks = split_note(title, content)
        vectors = _embed(chunks)
        self._ensure_collection(len(vectors[0]))
        self.delete_note(owner_id, note_id)
        points = []
        for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            point_id = str(uuid5(NAMESPACE_URL, f"note-chunk:{owner_id}:{note_id}:{index}"))
            points.append(
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": {
                        "owner_id": owner_id,
                        "note_id": note_id,
                        "chunk_index": index,
                        "title": title,
                        "chunk": chunk,
                        "chunk_id": f"{note_id}-{index:04d}",
                        "title_path": _title_path(chunk, title),
                        "chunk_char_count": len(chunk),
                    },
                },
            )
        self._request("PUT", f"/collections/{self.collection}/points", params={"wait": "true"}, json={"points": points})
        logger.info(
            "vector_note_indexed",
            extra={
                "event": "vector_note_indexed", "owner_id": owner_id, "note_id": note_id,
                "chunk_count": len(points), "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return len(points)

    def delete_note(self, owner_id: int, note_id: int) -> None:
        self._request(
            "POST",
            f"/collections/{self.collection}/points/delete",
            params={"wait": "true"},
            json={"filter": {"must": [_match("owner_id", owner_id), _match("note_id", note_id)]}},
            allow_not_found=True,
        )

    def delete_owner(self, owner_id: int) -> None:
        self._request(
            "POST",
            f"/collections/{self.collection}/points/delete",
            params={"wait": "true"},
            json={"filter": {"must": [_match("owner_id", owner_id)]}},
            allow_not_found=True,
        )

    def search(self, owner_id: int, query: str, limit: int) -> list[VectorHit]:
        started = time.perf_counter()
        vector = _embed([query])[0]
        payload = self._request(
            "POST",
            f"/collections/{self.collection}/points/search",
            json={
                "vector": vector,
                "limit": limit,
                "score_threshold": self.score_threshold,
                "with_payload": True,
                "filter": {"must": [_match("owner_id", owner_id)]},
            },
            allow_not_found=True,
        )
        hits: list[VectorHit] = []
        for item in payload.get("result", []) if payload else []:
            data = item.get("payload") or {}
            score = float(item.get("score", 0))
            if isinstance(data.get("note_id"), int) and score >= self.score_threshold:
                hits.append(VectorHit(note_id=data["note_id"], chunk=str(data.get("chunk", "")), score=score))
        logger.info(
            "vector_search_completed",
            extra={
                "event": "vector_search_completed", "owner_id": owner_id,
                "hit_count": len(hits), "top_score": round(hits[0].score, 4) if hits else 0,
                "threshold": self.score_threshold,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return hits

    def check(self) -> None:
        self._request("GET", "/healthz")

    def _ensure_collection(self, dimensions: int) -> None:
        cache_key = (self.url, self.collection)
        if cache_key in _PREPARED_COLLECTIONS:
            return
        response = self._request("GET", f"/collections/{self.collection}", allow_not_found=True)
        if not response:
            self._request(
                "PUT",
                f"/collections/{self.collection}",
                json={"vectors": {"size": dimensions, "distance": "Cosine"}},
            )
        for field_name in ("owner_id", "note_id"):
            self._request(
                "PUT",
                f"/collections/{self.collection}/index",
                params={"wait": "true"},
                json={"field_name": field_name, "field_schema": "integer"},
            )
        _PREPARED_COLLECTIONS.add(cache_key)

    def _request(self, method: str, path: str, allow_not_found: bool = False, **kwargs) -> dict:
        headers = {"api-key": self.api_key} if self.api_key else {}
        with httpx.Client(base_url=self.url, timeout=self.timeout, headers=headers) as client:
            response = client.request(method, path, **kwargs)
        if allow_not_found and response.status_code == 404:
            return {}
        response.raise_for_status()
        if not response.content:
            return {}
        if "application/json" not in response.headers.get("content-type", ""):
            return {}
        data = response.json()
        if data.get("status") not in {None, "ok"}:
            raise RuntimeError(f"Qdrant operation failed: {data.get('status')}")
        return data


def _match(key: str, value: int) -> dict:
    return {"key": key, "match": {"value": value}}


def _title_path(chunk: str, title: str) -> str:
    """提取 Markdown/中文章节上下文，作为可解释引用元数据。"""
    headings = re.findall(r"^#{1,6}\s+(.+)$|^(第[一二三四五六七八九十0-9]+[章节部分].*)$", chunk, flags=re.MULTILINE)
    values = [a or b for a, b in headings if a or b]
    return " / ".join(values[:3]) or title.strip()


@lru_cache
def _embedding_model():
    from fastembed import TextEmbedding

    settings = get_settings()
    model_options = {
        "model_name": settings.embedding_model,
        "cache_dir": settings.embedding_cache_dir,
        "local_files_only": settings.embedding_local_files_only,
    }
    if settings.embedding_model_path:
        model_options["specific_model_path"] = settings.embedding_model_path
    return TextEmbedding(**model_options)


def _embed(texts: Iterable[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _embedding_model().embed(list(texts))]
