"""可诊断的混合 RAG Pipeline、Reranker 与 Hook 生命周期。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
import logging
import re
from typing import Protocol

from app import rag
from app.config import get_settings
from app.vector_store import VectorHit


logger = logging.getLogger(__name__)


class NoteLike(Protocol):
    id: int
    title: str
    content: str


@dataclass(frozen=True)
class RagCandidate:
    note: NoteLike
    chunk: str
    dense_score: float = 0.0
    sparse_score: float = 0.0
    fusion_score: float = 0.0
    rerank_score: float = 0.0
    evidence_score: float = 0.0
    source_trust: float = 0.0
    retrieval_sources: tuple[str, ...] = ()


@dataclass
class RagContext:
    owner_id: int
    original_query: str
    query: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RagOutcome:
    query: str
    candidates: list[RagCandidate]
    evidence: list[RagCandidate]
    accepted: bool
    confidence: float
    reason: str
    confidence_components: dict[str, float] = field(default_factory=dict)


class RagHook(Protocol):
    name: str
    def before_retrieve(self, context: RagContext) -> None: ...
    def after_retrieve(self, context: RagContext, candidates: list[RagCandidate]) -> list[RagCandidate]: ...
    def after_rerank(self, context: RagContext, candidates: list[RagCandidate]) -> list[RagCandidate]: ...
    def on_low_confidence(self, context: RagContext, outcome: RagOutcome) -> None: ...


class BaseRagHook:
    name = "base"
    def before_retrieve(self, context: RagContext) -> None:  # noqa: ARG002
        return None
    def after_retrieve(self, context: RagContext, candidates: list[RagCandidate]) -> list[RagCandidate]:  # noqa: ARG002
        return candidates
    def after_rerank(self, context: RagContext, candidates: list[RagCandidate]) -> list[RagCandidate]:  # noqa: ARG002
        return candidates
    def on_low_confidence(self, context: RagContext, outcome: RagOutcome) -> None:  # noqa: ARG002
        return None


class NormalizeQueryHook(BaseRagHook):
    """检索前统一空白和常见口语前缀，保留原问题给生成模型。"""
    name = "normalize_query"
    def before_retrieve(self, context: RagContext) -> None:
        query = re.sub(r"\s+", " ", context.query).strip()
        context.query = re.sub(r"^(请问|麻烦|帮我|请帮我)[，,：:\s]*", "", query).strip() or query


class DeduplicateHook(BaseRagHook):
    """同一笔记只保留最高分块，避免上下文重复挤占 token。"""
    name = "deduplicate"
    def after_retrieve(self, context: RagContext, candidates: list[RagCandidate]) -> list[RagCandidate]:  # noqa: ARG002
        best: dict[int, RagCandidate] = {}
        for candidate in candidates:
            current = best.get(candidate.note.id)
            if current is None or candidate.fusion_score > current.fusion_score:
                best[candidate.note.id] = candidate
        return sorted(best.values(), key=lambda item: item.fusion_score, reverse=True)


class ConfidenceGuardHook(BaseRagHook):
    """记录低置信度原因，便于线上告警、人工标注和评测闭环。"""
    name = "confidence_guard"
    def on_low_confidence(self, context: RagContext, outcome: RagOutcome) -> None:
        logger.warning(
            "rag_low_confidence",
            extra={
                "event": "rag_low_confidence", "owner_id": context.owner_id,
                "confidence": round(outcome.confidence, 4), "reason": outcome.reason,
                "candidate_count": len(outcome.candidates),
            },
        )


HOOK_REGISTRY: dict[str, type[BaseRagHook]] = {
    hook.name: hook for hook in (NormalizeQueryHook, DeduplicateHook, ConfidenceGuardHook)
}


def build_hooks(names: str | None = None) -> list[RagHook]:
    configured = names if names is not None else get_settings().rag_hooks
    hooks: list[RagHook] = []
    for name in (item.strip().lower() for item in configured.split(",")):
        if not name:
            continue
        hook_type = HOOK_REGISTRY.get(name)
        if hook_type is None:
            raise ValueError(f"unknown RAG hook: {name}")
        hooks.append(hook_type())
    return hooks


class RagPipeline:
    def __init__(self, hooks: list[RagHook] | None = None) -> None:
        self.settings = get_settings()
        self.hooks = hooks if hooks is not None else build_hooks()

    def run(
        self,
        owner_id: int,
        question: str,
        notes: list[NoteLike],
        vector_hits: list[VectorHit] | None = None,
    ) -> RagOutcome:
        context = RagContext(owner_id=owner_id, original_query=question, query=question)
        for hook in self.hooks:
            hook.before_retrieve(context)

        candidates = self._hybrid_retrieve(context.query, notes, vector_hits or [])
        for hook in self.hooks:
            candidates = hook.after_retrieve(context, candidates)
        candidates = self._rerank(context.query, candidates)
        for hook in self.hooks:
            candidates = hook.after_rerank(context, candidates)

        outcome = self._evaluate(context.query, candidates)
        if not outcome.accepted:
            for hook in self.hooks:
                hook.on_low_confidence(context, outcome)
        logger.info(
            "rag_pipeline_completed",
            extra={
                "event": "rag_pipeline_completed", "owner_id": owner_id,
                "candidate_count": len(candidates), "confidence": round(outcome.confidence, 4),
                "outcome": "accepted" if outcome.accepted else "abstained",
            },
        )
        return outcome

    def _hybrid_retrieve(
        self, query: str, notes: list[NoteLike], vector_hits: list[VectorHit],
    ) -> list[RagCandidate]:
        note_map = {note.id: note for note in notes}
        dense_best: dict[int, VectorHit] = {}
        for hit in vector_hits:
            if hit.note_id in note_map and (hit.note_id not in dense_best or hit.score > dense_best[hit.note_id].score):
                dense_best[hit.note_id] = hit

        documents = [f"{note.title}\n{note.content[:1500]}" for note in notes]
        sparse_raw = rag.bm25_scores(query, documents)
        # 中文按字/二元组分词时，两个完全无关的句子也可能偶然共享一个汉字。
        # BM25 会给这种碰撞非零分，因此先用“查询词覆盖率”剔除弱词法证据。
        for index, document in enumerate(documents):
            if rag.keyword_score(query, document) < 0.12:
                sparse_raw[index] = 0.0
        sparse_normalized = _normalize(sparse_raw)
        sparse_rank = sorted(range(len(notes)), key=lambda index: sparse_raw[index], reverse=True)
        dense_rank = sorted(dense_best, key=lambda note_id: dense_best[note_id].score, reverse=True)
        dense_positions = {note_id: index + 1 for index, note_id in enumerate(dense_rank)}
        sparse_positions = {notes[index].id: rank + 1 for rank, index in enumerate(sparse_rank) if sparse_raw[index] > 0}

        candidates: list[RagCandidate] = []
        for index, note in enumerate(notes):
            dense = dense_best.get(note.id)
            sparse = sparse_normalized[index] if sparse_raw[index] > 0 else 0.0
            if dense is None and sparse <= 0:
                continue
            sources = tuple(source for source, present in (("dense", dense is not None), ("sparse", sparse > 0)) if present)
            # Reciprocal Rank Fusion 对不同分数量纲稳定，随后保留原始特征供 Reranker 使用。
            rrf = 0.0
            if note.id in dense_positions:
                rrf += 1 / (60 + dense_positions[note.id])
            if note.id in sparse_positions:
                rrf += 1 / (60 + sparse_positions[note.id])
            chunk = dense.chunk if dense else f"{note.title}\n{note.content[:500]}"
            candidates.append(RagCandidate(
                note=note, chunk=chunk, dense_score=dense.score if dense else 0.0,
                sparse_score=sparse, fusion_score=rrf, retrieval_sources=sources,
            ))
        return sorted(candidates, key=lambda item: item.fusion_score, reverse=True)[:self.settings.rag_candidate_limit]

    def _rerank(self, query: str, candidates: list[RagCandidate]) -> list[RagCandidate]:
        if not candidates:
            return []
        mode = self.settings.rag_reranker.lower()
        if mode == "cross_encoder":
            try:
                scores = _cross_encoder_scores(query, [item.chunk for item in candidates])
                ranked = [replace(item, rerank_score=max(0.0, min(1.0, score))) for item, score in zip(candidates, scores, strict=True)]
                return sorted(ranked, key=lambda item: item.rerank_score, reverse=True)[:self.settings.rag_reranker_top_n]
            except Exception:
                logger.exception("Cross-encoder reranker failed; falling back to hybrid reranker")
        if mode == "off":
            return [replace(item, rerank_score=item.fusion_score) for item in candidates[:self.settings.rag_reranker_top_n]]

        dense = _normalize([item.dense_score for item in candidates])
        fusion = _normalize([item.fusion_score for item in candidates])
        ranked: list[RagCandidate] = []
        for index, item in enumerate(candidates):
            lexical = rag.keyword_score(query, f"{item.note.title} {item.chunk}")
            title_match = rag.keyword_score(query, item.note.title)
            score = dense[index] * 0.35 + item.sparse_score * 0.30 + fusion[index] * 0.15 + lexical * 0.15 + title_match * 0.05
            ranked.append(replace(item, rerank_score=max(0.0, min(1.0, score))))
        return sorted(ranked, key=lambda item: item.rerank_score, reverse=True)[:self.settings.rag_reranker_top_n]

    def _evaluate(self, query: str, candidates: list[RagCandidate]) -> RagOutcome:
        if not candidates:
            return RagOutcome(query, [], [], False, 0.0, "no_candidate")

        # Rerank/RRF 只决定顺序，不能单独证明相关性。尤其在候选很少时，min-max
        # 归一化会把一个弱候选抬成 1.0。这里改用每条候选自己的绝对证据分数做门控：
        # 稠密相似度是主信号，词法覆盖和 BM25 只做增强；完全没有词法重合时，
        # 必须达到更严格的强语义阈值才允许引用。
        scored: list[RagCandidate] = []
        annotated: list[RagCandidate] = []
        for candidate in candidates:
            dense = max(0.0, min(1.0, candidate.dense_score))
            sparse = max(0.0, min(1.0, candidate.sparse_score))
            document = f"{candidate.note.title} {candidate.chunk}"
            lexical = rag.keyword_score(query, document)
            evidence_score = dense * 0.65 + lexical * 0.25 + sparse * 0.10
            source_trust = self._source_trust(candidate)
            candidate = replace(
                candidate,
                evidence_score=evidence_score,
                source_trust=source_trust,
            )
            annotated.append(candidate)
            has_grounding = (
                lexical >= self.settings.rag_min_lexical_score
                or dense >= self.settings.rag_semantic_only_score_threshold
            )
            if (
                rag.entity_compatible(query, document)
                and has_grounding
                and evidence_score >= self.settings.rag_min_confidence
            ):
                scored.append(candidate)

        if not scored:
            return RagOutcome(
                query, annotated, [], False, 0.0, "no_citable_evidence",
                {"relevance": 0.0, "margin": 0.0, "retrieval_support": 0.0, "source_trust": 0.0},
            )

        top = scored[0]
        competing_scores = sorted(
            (item.evidence_score for item in annotated if item.note.id != top.note.id),
            reverse=True,
        )
        second_score = competing_scores[0] if competing_scores else 0.0
        relevance = _saturate(top.evidence_score, self.settings.rag_citation_relevance_saturation)
        margin = _saturate(
            max(0.0, top.evidence_score - second_score),
            self.settings.rag_citation_margin_saturation,
        )
        retrieval_support = 1.0 if {"dense", "sparse"}.issubset(top.retrieval_sources) else 0.85
        confidence = (
            relevance * 0.60
            + margin * 0.15
            + retrieval_support * 0.15
            + top.source_trust * 0.10
        )
        components = {
            "relevance": relevance,
            "margin": margin,
            "retrieval_support": retrieval_support,
            "source_trust": top.source_trust,
            "top_evidence_score": top.evidence_score,
            "second_evidence_score": second_score,
        }
        accepted = confidence >= self.settings.rag_citation_confidence_threshold
        reason = "accepted" if accepted else "citation_confidence_below_threshold"
        return RagOutcome(
            query, annotated, scored if accepted else [], accepted, confidence, reason, components,
        )

    def _source_trust(self, candidate: RagCandidate) -> float:
        """返回显式来源策略分，不伪装成事实真伪概率。

        当前只有仓库维护的 agent-showcase 资料具有可验证来源标识；普通用户笔记
        使用保守默认值。未来接入来源域名、作者、审核状态后再替换这一策略。
        """
        source_key = str(getattr(candidate.note, "source_key", "") or "")
        if source_key.startswith("agent-showcase:"):
            return self.settings.rag_source_trust_curated
        return self.settings.rag_source_trust_default


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high <= low:
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _saturate(value: float, saturation: float) -> float:
    """把可解释的绝对信号映射到 0..1；saturation 必须由配置保证大于 0。"""
    return max(0.0, min(1.0, value / saturation))


@lru_cache
def _cross_encoder():
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    settings = get_settings()
    options = {"model_name": settings.rag_reranker_model, "cache_dir": settings.embedding_cache_dir}
    if settings.rag_reranker_model_path:
        options["specific_model_path"] = settings.rag_reranker_model_path
    return TextCrossEncoder(**options)


def _cross_encoder_scores(query: str, documents: list[str]) -> list[float]:
    return [float(score) for score in _cross_encoder().rerank(query, documents)]
