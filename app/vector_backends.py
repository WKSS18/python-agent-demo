"""向量存储端口与工厂。

业务层只依赖这个最小协议。当前生产实现是 Qdrant；若将来切换 pgvector、Milvus
或 Elasticsearch，只需要新增适配器并在工厂注册，不必修改 Agent 和 Service。
"""

from __future__ import annotations

from typing import Protocol

from app.config import get_settings
from app.vector_store import VectorHit, VectorStore


class VectorBackend(Protocol):
    def index_note(self, owner_id: int, note_id: int, title: str, content: str) -> int: ...
    def delete_note(self, owner_id: int, note_id: int) -> None: ...
    def delete_owner(self, owner_id: int) -> None: ...
    def search(self, owner_id: int, query: str, limit: int) -> list[VectorHit]: ...
    def check(self) -> None: ...


def create_vector_backend() -> VectorBackend:
    """根据受控配置创建向量库适配器，拒绝静默使用未知供应商。"""
    provider = get_settings().vector_store_provider.lower().strip()
    if provider == "qdrant":
        return VectorStore()
    raise ValueError(f"unsupported vector store provider: {provider}")
