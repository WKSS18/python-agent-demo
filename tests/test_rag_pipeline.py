import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import agent, rag
from app.rag_pipeline import RagPipeline, build_hooks
from app.vector_store import VectorHit


class Note:
    def __init__(self, note_id: int, title: str, content: str) -> None:
        self.id = note_id
        self.title = title
        self.content = content


def settings(**overrides):
    values = {
        "rag_hooks": "normalize_query,deduplicate,confidence_guard",
        "rag_candidate_limit": 12,
        "rag_reranker": "hybrid",
        "rag_reranker_top_n": 5,
        "rag_min_confidence": 0.35,
        "rag_min_top_score": 0.35,
        "rag_min_score_margin": 0.01,
        "rag_min_lexical_score": 0.12,
        "rag_semantic_only_score_threshold": 0.72,
        "rag_citation_confidence_threshold": 0.85,
        "rag_citation_relevance_saturation": 0.60,
        "rag_citation_margin_saturation": 0.15,
        "rag_source_trust_default": 0.80,
        "rag_source_trust_curated": 0.95,
        "rag_reranker_model": "unused",
        "rag_reranker_model_path": "",
        "embedding_cache_dir": ".cache",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class SparseRetrievalTests(unittest.TestCase):
    def test_bm25_prefers_document_with_rare_query_terms(self) -> None:
        scores = rag.bm25_scores(
            "退款审批",
            ["员工考勤和请假说明", "客户退款审批流程与财务复核", "产品使用手册"],
        )
        self.assertEqual(scores.index(max(scores)), 1)

    def test_generic_question_words_do_not_create_bm25_evidence(self) -> None:
        self.assertEqual(rag.keyword_score("vue3介绍下", "react测试 测试一下"), 0.0)
        self.assertEqual(rag.keyword_score("vue3介绍下", "言语理解题 下文内容"), 0.0)
        self.assertGreater(rag.keyword_score("vue3介绍下", "Vue 3 组合式 API"), 0.0)

    def test_framework_entity_conflict_is_detected(self) -> None:
        self.assertFalse(rag.entity_compatible("vue3介绍下", "React hooks 使用说明"))
        self.assertTrue(rag.entity_compatible("vue3和react区别", "Vue 与 React 对比"))
        self.assertFalse(rag.entity_compatible("vue3介绍下", "组合式 API 和响应式系统"))


class RagPipelineTests(unittest.TestCase):
    def test_hybrid_retrieval_and_rerank_select_relevant_note(self) -> None:
        notes = [
            Note(1, "请假制度", "员工请假需要主管审批"),
            Note(2, "退款流程", "客户退款需要财务复核并原路退回"),
        ]
        hits = [
            VectorHit(note_id=1, chunk="请假制度\n员工请假", score=0.61),
            VectorHit(note_id=2, chunk="退款流程\n客户退款需要财务复核", score=0.83),
        ]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate,confidence_guard")).run(
                7, "请问 客户退款怎么审批", notes, hits,
            )
        self.assertTrue(outcome.accepted)
        self.assertEqual(outcome.candidates[0].note.id, 2)
        self.assertIn("dense", outcome.candidates[0].retrieval_sources)
        self.assertIn("sparse", outcome.candidates[0].retrieval_sources)
        self.assertEqual([item.note.id for item in outcome.evidence], [2])

    def test_unrelated_query_abstains_instead_of_citing_note(self) -> None:
        notes = [Note(1, "请假制度", "员工请假需要主管审批")]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate,confidence_guard")).run(
                7, "量子芯片最新制程", notes, [],
            )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.reason, "no_candidate")
        self.assertEqual(outcome.candidates, [])
        self.assertEqual(outcome.evidence, [])

    def test_weak_dense_hits_without_lexical_grounding_are_not_cited(self) -> None:
        notes = [
            Note(1, "公务员言语理解", "判断题目主旨并选择答案"),
            Note(2, "社区工作者招聘", "报名序号和准考证说明"),
            Note(3, "入职体检提示", "携带身份证并按导引单体检"),
        ]
        hits = [
            VectorHit(note_id=1, chunk="公务员言语理解题", score=0.68),
            VectorHit(note_id=2, chunk="社区工作者招聘公告", score=0.66),
            VectorHit(note_id=3, chunk="入职体检提示", score=0.63),
        ]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate")).run(
                7, "transform有哪些属性", notes, hits,
            )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.reason, "no_citable_evidence")
        self.assertEqual(outcome.evidence, [])

    def test_only_individually_qualified_candidates_become_evidence(self) -> None:
        notes = [
            Note(1, "CSS transform", "transform 支持 translate rotate scale skew matrix"),
            Note(2, "社区工作者招聘", "报名序号和准考证说明"),
        ]
        hits = [
            VectorHit(note_id=1, chunk="transform 支持 translate rotate scale", score=0.82),
            VectorHit(note_id=2, chunk="社区工作者招聘公告", score=0.64),
        ]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate")).run(
                7, "transform有哪些属性", notes, hits,
            )
        self.assertTrue(outcome.accepted)
        self.assertEqual([item.note.id for item in outcome.evidence], [1])

    def test_strong_semantic_match_can_pass_without_literal_overlap(self) -> None:
        notes = [Note(1, "页面二维变换", "元素可以平移、旋转、缩放和倾斜")]
        hits = [VectorHit(note_id=1, chunk="元素可以平移、旋转、缩放和倾斜", score=0.79)]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate")).run(
                7, "CSS transform functions", notes, hits,
            )
        self.assertTrue(outcome.accepted)
        self.assertEqual([item.note.id for item in outcome.evidence], [1])

    def test_vue_query_rejects_react_and_generic_long_document(self) -> None:
        notes = [
            Note(6, "react测试", "react测试 测试一下"),
            Note(7, "言语必刷100题", "介绍文章主旨并根据下文选择答案"),
        ]
        hits = [
            VectorHit(note_id=6, chunk="react测试 测试一下", score=0.582839),
            VectorHit(note_id=7, chunk="介绍文章主旨并根据下文选择答案", score=0.555818),
        ]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate")).run(
                7, "vue3介绍下", notes, hits,
            )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.evidence, [])

    def test_vue_query_accepts_relevant_vue_note(self) -> None:
        notes = [Note(8, "Vue 3", "组合式 API、响应式系统、Teleport 和 Suspense")]
        hits = [VectorHit(note_id=8, chunk="Vue 3 组合式 API 和响应式系统", score=0.62)]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate")).run(
                7, "vue3介绍下", notes, hits,
            )
        self.assertTrue(outcome.accepted)
        self.assertEqual([item.note.id for item in outcome.evidence], [8])

    def test_high_relevance_but_ambiguous_top_scores_fail_final_gate(self) -> None:
        notes = [
            Note(1, "退款审批流程 A", "退款审批需要财务复核"),
            Note(2, "退款审批流程 B", "退款审批需要主管复核"),
        ]
        hits = [
            VectorHit(note_id=1, chunk="退款审批需要财务复核", score=0.82),
            VectorHit(note_id=2, chunk="退款审批需要主管复核", score=0.819),
        ]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate")).run(
                7, "退款审批流程", notes, hits,
            )
        self.assertFalse(outcome.accepted)
        self.assertEqual(outcome.reason, "citation_confidence_below_threshold")
        self.assertLess(outcome.confidence_components["margin"], 0.1)

    def test_curated_source_has_higher_explicit_trust_score(self) -> None:
        curated = Note(1, "FastAPI", "FastAPI 使用 Pydantic 校验参数")
        curated.source_key = "agent-showcase:2026.08.1:architecture"
        hits = [VectorHit(note_id=1, chunk="FastAPI 使用 Pydantic 校验参数", score=0.82)]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate")).run(
                7, "FastAPI 参数校验", [curated], hits,
            )
        self.assertTrue(outcome.accepted)
        self.assertEqual(outcome.confidence_components["source_trust"], 0.95)

    def test_deduplicate_keeps_only_best_chunk_per_note(self) -> None:
        notes = [Note(1, "退款", "退款审批和退款到账说明")]
        hits = [
            VectorHit(note_id=1, chunk="退款审批", score=0.80),
            VectorHit(note_id=1, chunk="退款到账", score=0.70),
        ]
        with patch("app.rag_pipeline.get_settings", return_value=settings()):
            outcome = RagPipeline(hooks=build_hooks("normalize_query,deduplicate")).run(7, "退款审批", notes, hits)
        self.assertEqual(len(outcome.candidates), 1)
        self.assertEqual(outcome.candidates[0].chunk, "退款审批")


class FineTunedModelRoutingTests(unittest.TestCase):
    def test_fine_tuned_model_is_only_used_with_accepted_rag_notes(self) -> None:
        model_settings = SimpleNamespace(
            rag_fine_tuned_model_enabled=True,
            rag_fine_tuned_model="fieldnote-answer-lora-v1",
        )
        note = SimpleNamespace(title="流程", content="可靠上下文")
        with (
            patch("app.agent.get_settings", return_value=model_settings),
            patch("app.agent._stream_model", return_value=iter(["ok"])) as stream,
        ):
            self.assertEqual(list(agent.stream_answer("问题", [note])), ["ok"])
            self.assertEqual(stream.call_args.kwargs["model"], "fieldnote-answer-lora-v1")
            list(agent.stream_answer("问题", []))
            self.assertIsNone(stream.call_args.kwargs["model"])


if __name__ == "__main__":
    unittest.main()
