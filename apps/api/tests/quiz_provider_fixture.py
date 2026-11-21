"""Synthetic provider responses for the two stages of a grounded five-question set."""
def quiz_batch_response(data):
    if 'tasks' in data:
        return {key:dict(stem=f"{key}의 올바른 설명은?", options=["첫 번째","두 번째","세 번째","네 번째"],
                         answer_index=0,explanation="자료에 나온 순서로 처리합니다.",hint="양 끝 위치를 떠올려 보세요.",
                         source_id=next(iter(data['passages']))) for key in data['tasks']}
    if 'answer_index' in next(iter(data.values())):
        return {key:dict(supported=True,unambiguous=True,answer_correct=True,explanation_supported=True,
                         hint_appropriate=True,concept_matches=True,distinct_objective=True,reason="합성 근거") for key in data}
    return {key:dict(correct_indices=[item['options'].index("첫 번째")],supported=True,task_fits=True,concept_matches=True,
                     reason="독립 합성 확인") for key,item in data.items()}


def quiz_response(data):
    source = data["evidence"]["sources"][0]
    common = {"answer_index": 0, "source_id": source["id"], "quote": source["text"].splitlines()[0],
              "explanation": "접시를 쌓듯 자료에 나온 순서로 처리합니다.", "hint": "처음과 마지막 위치를 비교해 보세요."}
    if "assessment_task" in data:
        return {**common, "stem": f"{data['assessment_task'].split('(')[0]}의 올바른 설명은?",
                "options": ["첫 번째", "두 번째", "세 번째", "네 번째"], "concept_id": data["concept_id"],
                "difficulty": data["difficulty"], "difficulty_reason": "합성 검증"}
    return {**common, "supported": True, "single_correct": True, "explanation_supported": True,
            "difficulty_matches": True, "reason": "합성 자료 확인"}
