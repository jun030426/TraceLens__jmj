"""Progressive practice support. No code execution and no hidden answers in views."""
import ast

from sqlalchemy import select

from lerny.models import AuditEvent, PracticeAttempt


def metadata(exercise):
    helpers = []
    requirements = ["시작 코드의 입력 선언을 유지하세요.", "입력 값이 달라져도 같은 처리 순서로 결과를 구하세요."]
    guide = ""
    if exercise.language == "python":
        # Only inspect already-visible starter code. Never publish reference bodies.
        try:
            tree = ast.parse(exercise.template.replace("[[빈칸]]", "None"))
            helpers = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        except (SyntaxError, ValueError):
            pass
        if exercise.kind == "full":
            from rag_mvp.cloze_generator import ClozeGenerator
            statement = ClozeGenerator.infer_problem_statement(exercise.reference, slide_text=exercise.prompt)
            requirements.extend(statement["requirements"])
            guide = ClozeGenerator.extract_available_helpers(exercise.reference, slide_text=exercise.prompt)["helpers_guide_text"]
    return {"requirements": requirements, "helpers_guide_text": guide,
            "available_helpers": list(dict.fromkeys(helpers)),
            "hint_steps": len(hints(exercise))}


def hints(exercise):
    if exercise.language == "python":
        from rag_mvp.cloze_generator import ClozeGenerator
        mode = "cloze" if exercise.kind == "blank" else "full_coding"
        code = "\n".join(exercise.blanks.values()) if mode == "cloze" else exercise.reference
        flow = ClozeGenerator.practice_hint_flow(exercise.title, mode, code)
        if mode == "cloze" or flow["flow_title"] != ClozeGenerator.GENERIC_ACTION_FLOW["flow_title"]:
            return [step["title"] + "\n" + step["action_story"] for step in flow["steps"]]
    # The teammate's action-flow pedagogy is adapted to the actual source. Avoid
    # their hard-coded stack/queue answers for unrelated lecture implementations.
    actions = []
    if exercise.language == "python":
        try:
            tree = ast.parse(exercise.reference)
            if any(isinstance(n, ast.If) for n in ast.walk(tree)):
                actions.append("조건이 참인 경우와 거짓인 경우를 나눠 입력 값의 변화를 따라가 보세요.")
            if any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(tree)):
                actions.append("반복 시작값, 한 번 처리한 뒤 바뀌는 값, 종료 조건을 순서대로 적어 보세요.")
            if any(isinstance(n, ast.Return) for n in ast.walk(tree)):
                actions.append("중간에 계산한 값 중 호출한 곳에 돌려줘야 하는 결과를 구분해 보세요.")
        except (SyntaxError, ValueError):
            pass
    result = [f"「{exercise.title}」에서 주어진 입력과 구해야 하는 출력을 먼저 구분해 보세요.",
              " ".join(actions[:2]) or "입력 → 처리 → 출력의 순서로 각 변수의 역할을 적어 보세요.",
              "예시 입력을 손으로 따라가며 각 단계의 값을 기록하고, 입력이 바뀌어도 같은 규칙이 적용되는지 확인하세요."]
    if exercise.kind == "full":
        result.append("입력 준비 → 필요한 상태 초기화 → 조건·반복 처리 → 결과 출력의 작은 단계로 나눠 구현하세요. 최종 제출한 뒤에는 답지·해설에서 모범 코드와 비교할 수 있어요.")
    return result


def help_state(session, actor, plan, exercise):
    events = list(session.scalars(select(AuditEvent).where(AuditEvent.actor_id == actor.id,
        AuditEvent.target_id == plan.id, AuditEvent.action == "practice_help",
        AuditEvent.detail["exercise_id"].as_string() == exercise.id)))
    used = max((int(e.detail.get("step", 0)) for e in events if e.detail.get("kind") == "hint"), default=0)
    steps = hints(exercise)
    used = min(len(steps), used)
    wrong = list(session.scalars(select(PracticeAttempt.id).where(PracticeAttempt.student_id == actor.id,
        PracticeAttempt.exercise_id == exercise.id, PracticeAttempt.practice_session_id == plan.id,
        PracticeAttempt.status == "graded", PracticeAttempt.correct.is_(False))))
    submitted_query = select(PracticeAttempt.id).where(PracticeAttempt.student_id == actor.id,
        PracticeAttempt.section_id == plan.section_id, PracticeAttempt.exercise_id == exercise.id)
    if plan.day is not None:
        submitted_query = submitted_query.where(PracticeAttempt.practice_session_id == plan.id)
    submitted = session.scalar(submitted_query.limit(1))
    return {"hints_used": used, "hints": steps[:used], "max_hint_steps": len(steps),
            "failed_attempts": len(wrong), "can_view_answer": submitted is not None,
            "independent": not bool(events)}


def explanation(exercise):
    """Only call after checking an owned final submission and current publication."""
    sample = exercise.tests[0]
    return {"title": exercise.title, "kind": exercise.kind, "language": exercise.language,
            "description": exercise.prompt, "requirements": metadata(exercise)["requirements"],
            "reference": exercise.reference,
            "blanks": list(exercise.blanks.values()) if exercise.kind == "blank" else [],
            "example_input": sample["input"], "expected": sample["expected"]}
