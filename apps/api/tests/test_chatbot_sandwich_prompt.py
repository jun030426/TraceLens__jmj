"""Unit tests for Pattern #2 (Question -> Details/Sources -> Question) chatbot prompt,
whitespace-normalized prose citation checks, and contextual follow-up helpers."""
import json
import unittest
from types import SimpleNamespace

from rag_mvp.pipeline import check_answer
from rag_mvp.unified_rag import UnifiedMultimodalRAG


class ChatbotSandwichPromptTests(unittest.TestCase):
    def test_sandwich_prompt_structure_and_no_duplication(self):
        from lerny.team_engine import ServiceGoogle

        captured = {}

        def fake_generate(prompt, schema):
            captured["prompt"] = prompt
            captured["schema"] = schema
            return {
                "answerable": True,
                "claims": [
                    {
                        "text": "스택은 후입선출(LIFO) 구조입니다.",
                        "source_id": "chunk-1",
                        "quote": "스택은 후입선출(LIFO) 구조이다.",
                    }
                ],
                "reason": "",
            }

        client = ServiceGoogle(
            generate=fake_generate,
            tutoring_instruction="용어를 풀어서 한 단계씩 설명한다.",
            student_context="학생 코드: stack.pop()",
        )
        hits = [
            {
                "id": "chunk-1",
                "text": "UNIQUE_SLIDE_BODY_123: 스택은 후입선출(LIFO) 구조이다.",
                "source_file": "week3.pptx",
                "slide_number": 4,
            }
        ]
        history = [
            {"role": "user", "content": "PREV_Q_UNIQUE_456"},
            {"role": "assistant", "content": "PREV_A_UNIQUE_789"},
        ]
        question = "스택의 pop 연산은 무엇인가요?"
        client.answer_chat_prompt(question, hits, history, "legacy ignored prompt")

        prompt = captured["prompt"]
        # 1. Pattern #2: Question appears at the very beginning and at the very end JSON
        self.assertTrue(prompt.startswith(f"학생 질문: {question}\n"))
        payload = json.loads(prompt.rsplit("\n", 1)[1])
        self.assertEqual(list(payload.keys()), ["memory", "sources", "question"])
        self.assertEqual(payload["question"], question)
        self.assertEqual(payload["sources"][0]["source_id"], "chunk-1")
        self.assertEqual(payload["memory"][0]["question"], "PREV_Q_UNIQUE_456")

        # 2. Sources and memory are sent strictly ONCE (no 2x duplication)
        self.assertEqual(prompt.count("UNIQUE_SLIDE_BODY_123"), 1)
        self.assertEqual(prompt.count("PREV_Q_UNIQUE_456"), 1)
        self.assertEqual(prompt.count("PREV_A_UNIQUE_789"), 1)

        # 3. Dynamic instruction & student context sit in the middle (after opening question, before JSON)
        q_pos = prompt.index(f"학생 질문: {question}")
        inst_pos = prompt.index("용어를 풀어서 한 단계씩 설명한다.")
        ctx_pos = prompt.index("학생 코드: stack.pop()")
        json_pos = prompt.rfind("\n{")
        self.assertLess(q_pos, inst_pos)
        self.assertLess(inst_pos, ctx_pos)
        self.assertLess(ctx_pos, json_pos)

        # 4. Contradictory analogy rule & hardcoded course name are removed
        self.assertNotIn("AI 초심자 비유 자동 보완", prompt)
        self.assertNotIn("알고리즘 및 자료구조", prompt)

    def test_theory_vs_practice_mode_rules_are_separated(self):
        from lerny.team_engine import ServiceGoogle

        prompts = {}
        hits = [{"id": "c1", "text": "예제:\n```python\nprint(1)\n```", "source_file": "w1.pptx", "slide_number": 1}]
        for mode in ("theory", "practice"):
            def capture(prompt, _schema, m=mode):
                prompts[m] = prompt
                return {"answerable": True, "claims": [], "reason": ""}
            client = ServiceGoogle(generate=capture, chat_mode=mode)
            client.answer_chat_prompt("예제 코드 설명해줘", hits, [], "")

        # 개인별(이론) 챗봇: 슬라이드 예제 코드 인용 설명 허용, 정답 코드 복붙 금지 문구 제외
        self.assertIn("슬라이드 예제 코드를 쉽게 풀어서 설명", prompts["theory"])
        self.assertIn("원문에 있는 예제 코드를 그대로 인용해 단계별로 설명해도 좋습니다", prompts["theory"])
        self.assertNotIn("완성된 정답 코드 통째 복붙 금지", prompts["theory"])

        # 실습 챗봇: 완성 정답 코드 복붙 금지 + 정답 코드 인용 금지 유지
        self.assertIn("완성된 정답 코드 통째 복붙 금지", prompts["practice"])
        self.assertIn("실습 모드에서는 정답 코드를 그대로 인용하거나", prompts["practice"])

    def test_supabase_index_verification_cache_hits_invalidates_and_expires(self):
        from unittest.mock import patch
        from lerny import retrieval

        retrieval.clear_index_cache()
        calls = []
        fake_store_1 = object()
        fake_store_2 = object()

        def make_rag_index(store_obj, present_ids):
            def indexed_ids(chunks):
                chunk_list = list(chunks)
                calls.append([c.id for c in chunk_list])
                return {c.id for c in chunk_list if c.id in present_ids}

            return SimpleNamespace(shared_store=lambda: store_obj, indexed_ids=indexed_ids)

        row1 = (SimpleNamespace(id="c1", content="스택은 LIFO다."), SimpleNamespace(week=1), SimpleNamespace(id="v1"))
        row2 = (SimpleNamespace(id="c2", content="큐는 FIFO다."), SimpleNamespace(week=1), SimpleNamespace(id="v1"))

        fake_mod = make_rag_index(fake_store_1, {"c1", "c2"})
        with patch.object(retrieval, "settings", return_value=SimpleNamespace(supabase_url="https://example.supabase.co")):
            with patch.object(retrieval.time, "monotonic", return_value=1000.0):
                # 1차 호출: 실제 Supabase 출석 체크 수행
                self.assertTrue(retrieval._supabase_index_verified("course-1", [row1, row2], fake_mod))
                self.assertEqual(len(calls), 1)
                # 2차 호출(동일 청크, TTL 이내): 캐시 히트 → RPC 호출 0회
                self.assertTrue(retrieval._supabase_index_verified("course-1", [row1, row2], fake_mod))
                self.assertEqual(len(calls), 1)

                # 자료 내용 변경 시: 지문이 바뀌어 즉시 재확인
                row2_edited = (SimpleNamespace(id="c2", content="큐는 선입선출이다."), SimpleNamespace(week=1), SimpleNamespace(id="v1"))
                self.assertTrue(retrieval._supabase_index_verified("course-1", [row1, row2_edited], fake_mod))
                self.assertEqual(len(calls), 2)

                # 다른 store 인스턴스(빈 인덱스 테스트 등)와는 캐시 절대 공유 안 함
                empty_mod = make_rag_index(fake_store_2, set())
                self.assertFalse(retrieval._supabase_index_verified("course-1", [row1, row2], empty_mod))
                self.assertEqual(len(calls), 3)

            # 1시간(3600초) TTL 만료 후 재확인
            with patch.object(retrieval.time, "monotonic", return_value=1000.0 + 3601.0):
                self.assertTrue(retrieval._supabase_index_verified("course-1", [row1, row2], fake_mod))
                self.assertEqual(len(calls), 4)

    def test_prose_quote_tolerates_ppt_newlines_and_extra_spaces(self):
        hit = {
            "id": "s1",
            "text": "스택은 마지막에 들어온\n데이터가   먼저 나가는 LIFO 구조이다.",
            "source_file": "lecture.pptx",
            "slide_number": 4,
        }
        candidate = {
            "answerable": True,
            "claims": [
                {
                    "text": "스택은 마지막에 들어온 데이터가 먼저 나갑니다.",
                    "source_id": "s1",
                    "quote": "스택은 마지막에 들어온 데이터가 먼저 나가는 LIFO 구조이다.",
                }
            ],
            "reason": "",
        }
        checked = check_answer(candidate, [hit], "스택이 뭐야?")
        self.assertEqual(checked["status"], "citation_checked")

        from lerny.rag_answers import Claim, citations_valid

        self.assertTrue(
            citations_valid(
                [Claim(text="t", source_id="s1", quote=candidate["claims"][0]["quote"])],
                {"s1": hit["text"]},
            )
        )

    def test_code_and_operator_mutations_remain_strictly_held(self):
        hit = {
            "id": "s1",
            "text": "계산식은 `a + b`이다.",
            "source_file": "lecture.pptx",
            "slide_number": 1,
        }
        bad = {
            "answerable": True,
            "claims": [
                {
                    "text": "계산식은 a * b입니다.",
                    "source_id": "s1",
                    "quote": "`a * b`",
                }
            ],
            "reason": "",
        }
        self.assertEqual(check_answer(bad, [hit])["status"], "held")

    def test_upstream_chat_topics_followup_detection(self):
        from lerny.chat_topics import EXAMPLE_REQUEST, mentions_topic, topic_terms

        self.assertEqual(topic_terms("예시를 설명해줘"), [])
        self.assertEqual(topic_terms("다시 쉽게 설명해줘"), [])
        self.assertTrue(bool(EXAMPLE_REQUEST.search("예시를 설명해줘")))
        self.assertEqual(topic_terms("upper()의 뜻은?"), ["upper"])
        self.assertTrue(mentions_topic("Call upper() on text.", ["upper"]))

    def test_interactive_worker_idle_sleep_is_faster_than_background_roles(self):
        from unittest.mock import patch
        from lerny import material_daemon

        self.assertEqual(material_daemon.IDLE_SLEEP_SECONDS["interactive"], 0.5)
        self.assertEqual(material_daemon.IDLE_SLEEP_SECONDS["material"], 2.0)
        self.assertEqual(material_daemon.IDLE_SLEEP_SECONDS["embedding"], 2.0)

        for role, expected in (("interactive", 0.5), ("material", 2.0), ("embedding", 2.0)):
            sleeps = []

            def fake_sleep(sec):
                sleeps.append(sec)
                raise SystemExit("done")

            with patch.object(material_daemon, "settings", return_value=SimpleNamespace(dedicated_worker=True)):
                with patch.object(material_daemon, "cleanup", lambda: None):
                    with patch.object(material_daemon, "run_once", return_value=False):
                        with patch.object(material_daemon.time, "sleep", fake_sleep):
                            with self.assertRaises(SystemExit):
                                material_daemon.main(role)
            self.assertEqual(sleeps, [expected])


if __name__ == "__main__":
    unittest.main()
