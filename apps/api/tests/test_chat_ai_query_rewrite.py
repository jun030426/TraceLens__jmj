"""Unit tests for LLM-based chat query rewriting and Korean follow-up topic normalization."""

import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _load_modules():
    """Import chat_topics and QueryRewrite/rewrite_chat_query cleanly even without full DB deps."""
    from lerny import chat_topics

    try:
        from lerny import rag_answers
        return chat_topics, rag_answers
    except Exception:
        # Lightweight test fallback when SQLAlchemy/Pydantic runtime deps are absent locally.
        return chat_topics, None


class ChatAIQueryRewriteTests(unittest.TestCase):
    def test_korean_particles_and_followup_phrases_are_normalized(self):
        chat_topics, _ = _load_modules()
        for q in (
            "다른 예시도 알려줘",
            "다른 예제도 보여줘",
            "비슷한 예시도 있어?",
            "또 다른 예시는?",
            "예시도 알려줘",
            "추가 설명도 해줘",
            "방금 거 다시 쉽게 설명해줘",
        ):
            self.assertEqual(chat_topics.topic_terms(q), [], f"should be follow-up: {q}")

        # Particle '에' attached after upper() must NOT leak into topic terms.
        self.assertEqual(chat_topics.topic_terms("upper()에 대해 설명해줘"), ["upper"])
        self.assertEqual(chat_topics.topic_terms("len()도 설명해줘"), ["len"])
        self.assertEqual(chat_topics.topic_terms("스택과 큐의 차이점은?"), ["스택", "큐"])
        self.assertEqual(chat_topics.topic_terms("연결 리스트를 설명해줘"), ["연결", "리스트"])

    def test_prior_citations_respects_mode_and_exercise_boundary(self):
        chat_topics, _ = _load_modules()
        history = [
            SimpleNamespace(
                question="실습 질문",
                learning_context={"mode": "practice", "exercise_id": "ex1"},
                answer={"answer_kind": "grounded", "citations": [{"chunk_id": "c_practice"}]},
            ),
            SimpleNamespace(
                question="upper()에 대해 설명해줘",
                learning_context={"mode": "theory"},
                answer={"answer_kind": "grounded", "citations": [{"chunk_id": "c_upper"}]},
            ),
        ]
        # Mode changed from theory -> practice -> theory: stops at practice boundary.
        self.assertEqual(chat_topics.prior_citations(history, {"mode": "theory"}), [])
        self.assertEqual(
            chat_topics.prior_citations(history, {"mode": "practice", "exercise_id": "ex1"}),
            ["c_practice"],
        )
        # Same mode: returns most recent grounded citations deduped.
        theory_history = [
            SimpleNamespace(
                question="다른 예시도 알려줘",
                learning_context={"mode": "theory"},
                answer={"answer_kind": "insufficient", "citations": []},
            ),
            SimpleNamespace(
                question="upper()에 대해 설명해줘",
                learning_context={"mode": "theory"},
                answer={
                    "answer_kind": "grounded",
                    "citations": [{"chunk_id": "c_upper"}, {"chunk_id": "c_upper"}],
                },
            ),
        ]
        self.assertEqual(chat_topics.prior_citations(theory_history, {"mode": "theory"}), ["c_upper"])

    def test_rewrite_chat_query_skips_first_turn_and_rewrites_multiturn(self):
        _, rag_answers = _load_modules()
        if rag_answers is None:
            self.skipTest("rag_answers runtime dependencies not installed in this Python environment")

        calls = []

        def fake_generate(prompt, schema):
            calls.append((prompt, schema))
            data = json.loads(prompt.rsplit("\n", 1)[1])
            self.assertIn("conversation_memory", data)
            return {
                "is_followup": True,
                "standalone_query": "upper() 다른 예시",
                "topic_keywords": ["upper"],
            }

        # Turn 1 (no memory): must NOT call model.
        self.assertIsNone(rag_answers.rewrite_chat_query("upper() 알려줘", [], {"mode": "theory"}, fake_generate))
        self.assertEqual(calls, [])

        # Turn 2 (with memory): calls model once and returns validated QueryRewrite.
        memory = [{"question": "upper()에 대해 설명해줘", "answer": "upper()는 대문자로 변환합니다."}]
        out = rag_answers.rewrite_chat_query("다른 예시도 알려줘", memory, {"mode": "theory"}, fake_generate)
        self.assertIsNotNone(out)
        self.assertTrue(out.is_followup)
        self.assertEqual(out.standalone_query, "upper() 다른 예시")
        self.assertEqual(out.topic_keywords, ["upper"])
        self.assertEqual(len(calls), 1)

    def test_rewrite_chat_query_falls_back_on_malformed_output_but_propagates_security_errors(self):
        _, rag_answers = _load_modules()
        if rag_answers is None:
            self.skipTest("rag_answers runtime dependencies not installed in this Python environment")

        memory = [{"question": "upper() 설명", "answer": "대문자 변환"}]
        # Malformed/legacy Answer-shaped reply falls back cleanly to None.
        self.assertIsNone(
            rag_answers.rewrite_chat_query(
                "다른 예시도 알려줘",
                memory,
                {"mode": "theory"},
                lambda *_: {"answerable": True, "claims": [], "reason": ""},
            )
        )

        # Broken JSON from model_json falls back cleanly to None instead of crashing chat.
        def raise_bad_json(*_):
            raise json.JSONDecodeError("bad json", "{", 1)

        self.assertIsNone(
            rag_answers.rewrite_chat_query("다른 예시도 알려줘", memory, {"mode": "theory"}, raise_bad_json)
        )

        # Generic request words returned inside topic_keywords must be stripped, not kept as topic filters.
        chat_topics, _ = _load_modules()
        cleaned = [term for kw in ["upper", "예시", "다른 예시"] for term in chat_topics.topic_terms(kw)]
        self.assertEqual(cleaned, ["upper"])

        # Security / source-change errors MUST propagate, never be swallowed.
        def raise_revoked(*_):
            raise ValueError("ACCESS_REVOKED")

        with self.assertRaisesRegex(ValueError, "ACCESS_REVOKED"):
            rag_answers.rewrite_chat_query("다른 예시도 알려줘", memory, {"mode": "theory"}, raise_revoked)

    def test_feedback_scores_swap_confused_and_unknown(self):
        from lerny import learning_signals

        self.assertEqual(
            learning_signals.FEEDBACK_SCORES,
            {"understood": 20, "confused": 65, "unknown": 80, "aborted": 80},
        )


if __name__ == "__main__":
    unittest.main()
