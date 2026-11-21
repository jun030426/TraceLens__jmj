import json
from types import SimpleNamespace

import pytest

from lerny.weekly_quiz import generate_set
from lerny.gemini_quota import request_purpose, review_job


def run(fault=None, persistent=False, *, verify_with_ai=True):
    chunk = SimpleNamespace(content="표에서 확인한 원문\n기호 == 와 != 를 구별합니다.")
    calls, sources = [], {}

    def model(prompt,schema):
        data = json.loads(prompt.rsplit("\n",1)[1])
        keys = list(schema["properties"])
        stage = "draft" if "tasks" in data else "review" if "answer_index" in data[keys[0]] else "blind"
        purpose = request_purpose("interactions", SimpleNamespace(gemini_review_quota_project="paid-test"))
        assert purpose == ("content" if stage == "draft" else "review")
        reject = (fault == stage and (persistent or not any(s == stage for s,_ in calls)))
        calls.append((stage,keys))
        result = {}
        for key in keys:
            if stage == "draft":
                result[key] = dict(stem=key+" 문항에서 맞는 설명은?", options=["정답","오답1","오답2","오답3"],
                    answer_index=0, explanation="표의 기호를 비교합니다.",hint="두 기호의 뜻을 떠올려 보세요.",source_id="E1")
                if reject and key == "Q3":
                    result[key]["explanation"] = "가"*81
            elif stage == "blind":
                assert data[key]["passage"] == chunk.content
                assert "answer_index" not in data[key] and "explanation" not in data[key]
                options = data[key]["options"]
                assert options[0] != "정답"
                assert data[key]["target_concept"] == "비교"
                result[key] = dict(correct_indices=[options.index("정답")],supported=True,task_fits=True,concept_matches=True,reason="원문 근거")
                if reject and key == "Q3":
                    result[key]["correct_indices"].append(options.index("오답1"))
            else:
                result[key] = dict(supported=True,unambiguous=True,answer_correct=True,explanation_supported=True,
                                   hint_appropriate=not (reject and key=="Q3"),concept_matches=True,distinct_objective=True,reason="힌트 확인")
                if key == "Q3" and fault in ("concept_matches","distinct_objective") and (persistent or len([s for s,_ in calls if s=="review"]) == 1):
                    result[key][fault] = False
        return result
    config = SimpleNamespace(gemini_review_quota_project="paid-test",gemini_review_course_id="course",gemini_review_week=4,
                             gemini_paid_generation_id=None)
    job = SimpleNamespace(course_id="course",kind="questions",payload={"generation_id":"synthetic"})
    with review_job(SimpleNamespace(scalar=lambda _:4),job,config):
        result = generate_set([(chunk,None,None)],SimpleNamespace(name="비교"),sources,model,verify_with_ai=verify_with_ai)
    return calls,result,sources,chunk


def test_instructor_review_retries_only_malformed_drafts():
    calls, result, sources, chunk = run("draft", verify_with_ai=False)
    assert calls == [("draft", ["Q1", "Q2", "Q3", "Q4", "Q5"]), ("draft", ["Q3"])]
    assert all(sources[q.sources[0].chunk_id] == (chunk, chunk.content) for q in result.questions)
    with pytest.raises(ValueError, match="QUESTION_VALIDATION_FAILED"):
        run("draft", persistent=True, verify_with_ai=False)


@pytest.mark.parametrize("fault",[None,"draft","blind","review","concept_matches","distinct_objective"])
def test_only_verified_items_survive_all_checks(fault):
    calls, result, sources, chunk = run(fault)
    assert len(result.questions) == len(sources) == 5
    assert all(sources[q.sources[0].chunk_id] == (chunk,chunk.content) for q in result.questions)
    rounds = [keys for stage,keys in calls if stage=="draft"]
    assert rounds == [["Q1","Q2","Q3","Q4","Q5"]]+([["Q3"]] if fault else [])


@pytest.mark.parametrize("fault",["draft","blind","review","concept_matches","distinct_objective"])
def test_persistent_failure_holds_entire_set(fault):
    with pytest.raises(ValueError,match="QUESTION_VALIDATION_FAILED"):
        run(fault,persistent=True)
