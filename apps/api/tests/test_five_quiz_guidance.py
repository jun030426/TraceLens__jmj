import json
from types import SimpleNamespace

from lerny.practice_support import hints, metadata
from lerny.team_engine import five_questions
from quiz_mvp.generation import TASKS


def test_teacher_quiz_uses_teammate_generator_and_reviewed_hints():
    source = SimpleNamespace(id="chunk", content="스택은 마지막에 들어온 원소를 먼저 꺼냅니다.", locator={})
    rows = [(source, SimpleNamespace(id="material", title="스택"), SimpleNamespace(id="v", filename="stack.pdf", sha256="a"*64))]
    received = []
    rejected_once = False

    def model(prompt, schema):
        nonlocal rejected_once
        data = json.loads(prompt.split("\n")[-1])
        assert 'quote' not in schema['properties']
        if "assessment_task" in data:
            received.append(data["assessment_task"])
            return dict(stem=f"문항 {len(received)}에서 옳은 설명은?", options=["가", "나", "다", "라"],
                        answer_index=0, explanation="접시를 쌓듯 마지막 원소부터 꺼냅니다.", hint="위치를 떠올려 보세요.",
                        concept_id="stack", difficulty=data["difficulty"], difficulty_reason="수업 목표",
                        source_id=data["evidence"]["sources"][0]["id"])
        assert len(data["evidence"]["sources"]) == 1 and "answer_index" not in data
        accepted = rejected_once
        rejected_once = True
        return dict(supported=True, single_correct=accepted, explanation_supported=True, difficulty_matches=True,
                    answer_index=0, reason="원문 확인", explanation="접시를 쌓듯 마지막 원소부터 꺼냅니다.",
                    hint="맨 위 접시의 위치를 떠올려 보세요.", source_id=data["evidence"]["sources"][0]["id"])

    sources, evidence = {}, []
    questions = five_questions(rows, "course", SimpleNamespace(id="stack", name="스택"), sources, evidence, model, "test-job").questions
    assert received == [TASKS[0], *TASKS]
    assert [q.kind for q in questions] == ["mcq"] * 5
    assert all(q.hint == "맨 위 접시의 위치를 떠올려 보세요." and "접시를 쌓듯" in q.explanation for q in questions)
    assert all(sources[q.sources[0].chunk_id] == (source, source.content) for q in questions)


def test_student_practice_guidance_uses_source_and_protects_blank_answers():
    code = "weight, height = 70, 175\nheight = height / 100\nbmi = weight / (height ** 2)\nprint(f'BMI : {bmi:.2f}')"
    ex = SimpleNamespace(title="BMI", language="python", kind="full", reference=code, template="weight, height = 70, 175",
                         prompt="키(cm)와 체중으로 BMI를 계산하세요.", blanks={})
    guide = metadata(ex)
    assert not guide["helpers_guide_text"] and guide["requirements"]
    assert len(hints(ex)) == 3
    ex.kind, ex.blanks = "blank", {"1": "bmi = weight / (height ** 2)"}
    assert len(hints(ex)) == 3 and all(hints(ex))
    assert ex.blanks["1"] not in str(hints(ex)) and not metadata(ex)["helpers_guide_text"]
