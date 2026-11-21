"""Progressive practice support. No code execution and no hidden answers in views."""
import ast


def metadata(exercise):
    requirements = [
        "시작 코드의 입력 변수 선언을 유지하세요.",
        "문제에서 요구한 핵심 연산 및 처리 순서를 준수하세요.",
        "출력 결과는 예시 출력 서식과 소수점 자릿수를 정확히 준수하세요."
    ]
    # 교안 및 문제 코드 기반의 범용 맞춤 요구조건 동적 생성 (BMI, 사칙연산, 성적, 정렬, 자료구조 등 모든 유형)
    if exercise.language == "python":
        ref_code = getattr(exercise, "reference", None) or getattr(exercise, "template", "") or ""
        try:
            from rag_mvp.cloze_generator import ClozeGenerator
            requirements = ClozeGenerator.infer_dynamic_requirements(ref_code, slide_text=exercise.prompt)
        except Exception:
            pass

    # 가이드라인(helpers_guide_text)은 계획대로 완전히 제거하여 화면을 깔끔하게 유지
    return {"requirements": requirements, "helpers_guide_text": "",
            "available_helpers": [],
            "hint_steps": len(hints(exercise))}


def hints(exercise):
    if exercise.language == "python":
        from rag_mvp.cloze_generator import ClozeGenerator
        if exercise.kind == "blank":
            # 빈칸 채우기: 빈칸 대상 슬롯(blanks)에 집중하여 3단계 비계(목적 -> 변수/문법 도구 -> 추상 골격) 힌트 생성
            raw_blanks = list(exercise.blanks.values()) if exercise.blanks else []
            code = "\n".join(raw_blanks) if raw_blanks else (exercise.reference or "")
            flow = ClozeGenerator.practice_hint_flow(exercise.title, "cloze", code)
        else:
            # 풀코딩: 전체 모범 코드(reference)를 기반으로 프로그램 구현 행동 흐름(Action Flow) 제공
            code = exercise.reference or ""
            flow = ClozeGenerator.practice_hint_flow(exercise.title, "full_coding", code)

        if flow and flow.get("steps"):
            return [step["title"] + "\n" + step["action_story"] for step in flow["steps"]]
        dynamic_flow = ClozeGenerator.generate_dynamic_action_flow(exercise.reference, title=exercise.title)
        if dynamic_flow and dynamic_flow.get("steps"):
            return [step["title"] + "\n" + step["action_story"] for step in dynamic_flow["steps"]]

    # Non-Python or AST-incompatible languages fallback
    result = [f"「{exercise.title}」에서 주어진 입력과 구해야 하는 출력을 먼저 구분해 보세요.",
              "입력 → 처리 → 출력의 순서로 각 변수의 역할을 적어 보세요.",
              "예시 입력을 손으로 따라가며 각 단계의 값을 기록하고, 입력이 바뀌어도 같은 규칙이 적용되는지 확인하세요."]
    if exercise.kind == "full":
        result.append("입력 준비 → 필요한 상태 초기화 → 조건·반복 처리 → 결과 출력의 작은 단계로 나눠 구현하세요.")
    return result


def help_state(session, actor, plan, exercise):
    from sqlalchemy import select
    from lerny.models import AuditEvent, PracticeAttempt

    events = list(session.scalars(select(AuditEvent).where(AuditEvent.actor_id == actor.id,
        AuditEvent.target_id == plan.id, AuditEvent.action == "practice_help",
        AuditEvent.detail["exercise_id"].as_string() == exercise.id)))
    used = max((int(e.detail.get("step", 0)) for e in events if e.detail.get("kind") == "hint"), default=0)
    steps = hints(exercise)
    used = min(len(steps), used)
    wrong = list(session.scalars(select(PracticeAttempt.id).where(PracticeAttempt.student_id == actor.id,
        PracticeAttempt.exercise_id == exercise.id, PracticeAttempt.practice_session_id == plan.id,
        PracticeAttempt.status == "graded", PracticeAttempt.correct.is_(False))))
    submitted = session.scalar(select(PracticeAttempt.id).where(
        PracticeAttempt.student_id == actor.id, PracticeAttempt.section_id == plan.section_id,
        PracticeAttempt.exercise_id == exercise.id, PracticeAttempt.practice_session_id == plan.id).limit(1))
    return {"hints_used": used, "hints": steps[:used], "max_hint_steps": len(steps),
            "failed_attempts": len(wrong), "can_view_answer": submitted is not None,
            "independent": not bool(events)}


def format_inline_comment(line: str) -> str:
    """코드 한 줄의 연산 의도를 분석하여 간결한 인라인 주석(# ...) 문구로 반환합니다."""
    line = line.strip()
    if not line:
        return ""
    # 원래 인라인 주석이 있으면 추출
    extracted_comment = ""
    if "#" in line:
        parts = line.split("#", 1)
        extracted_comment = parts[1].strip()
        line = parts[0].strip()

    # 특정 도메인(BMI, 사칙연산, 성적 등)에 대한 정밀 맞춤 주석
    l_lower = line.lower()
    if "height" in l_lower and ("/ 100" in line or "/100" in line):
        return extracted_comment or "키를 100으로 나누어 미터(m) 단위로 변환"
    if "bmi" in l_lower and ("weight" in l_lower or "** 2" in line or "**2" in line):
        return extracted_comment or "체질량지수(BMI) 공식 적용: 몸무게 / (키의 제곱)"
    if "print(" in line and ("bmi" in l_lower or ":.2f" in line):
        return extracted_comment or "계산된 BMI 결과를 소수 둘째 자리까지 포맷팅하여 출력"
    if "total" in l_lower and "+" in line:
        return extracted_comment or "과목 점수들을 모두 더하여 총점에 저장"
    if "avg" in l_lower and "/" in line:
        return extracted_comment or "총점을 과목 수로 나누어 평균 계산"
    if "self.top += 1" in line:
        return extracted_comment or "스택 최상단 포인터(top) 1 증가"
    if "self.top -= 1" in line:
        return extracted_comment or "스택 최상단 포인터(top) 1 감소"
    if "self.rear" in line and "%" in line:
        return extracted_comment or "큐 rear 포인터를 원형 회전 이동"

    if extracted_comment:
        return extracted_comment

    try:
        tree = ast.parse(line)
        if not tree.body:
            return ""
        stmt = tree.body[0]
        if isinstance(stmt, ast.Assign):
            target = ast.unparse(stmt.targets[0]) if hasattr(ast, "unparse") else "변수"
            val = stmt.value
            if isinstance(val, ast.BinOp):
                left_str = ast.unparse(val.left) if hasattr(ast, "unparse") else ""
                right_str = ast.unparse(val.right) if hasattr(ast, "unparse") else ""
                if isinstance(val.op, ast.Add):
                    return f"값들을 더해 {target}에 누적 합산"
                elif isinstance(val.op, (ast.Div, ast.FloorDiv)):
                    return f"{left_str}을 {right_str}으로 나누어 {target} 계산"
                elif isinstance(val.op, ast.Mult):
                    return f"{left_str}과 {right_str}을 곱하여 {target}에 저장"
                elif isinstance(val.op, ast.Sub):
                    return f"{left_str}에서 {right_str}을 뺀 값을 {target}에 저장"
                elif isinstance(val.op, ast.Pow):
                    return f"{left_str}의 {right_str} 거듭제곱을 계산하여 {target}에 저장"
                elif isinstance(val.op, ast.Mod):
                    return f"{left_str}을 {right_str}으로 나눈 나머지를 {target}에 저장"
            elif isinstance(val, ast.Compare):
                return f"조건을 비교 판별하여 {target}에 참/거짓 결과 저장"
            elif isinstance(val, ast.Call):
                func_name = getattr(val.func, "id", getattr(val.func, "attr", "함수"))
                if func_name == "len":
                    return f"전체 길이를 측정(len)하여 {target}에 저장"
                elif func_name in ("int", "float", "str"):
                    return f"{func_name}형으로 형변환하여 {target}에 저장"
                elif func_name == "input":
                    return f"사용자 입력을 받아 {target}에 저장"
                return f"{func_name}() 실행 결과를 {target}에 저장"
            return f"계산된 결과를 {target} 변수에 저장"
        elif isinstance(stmt, ast.AugAssign):
            target = getattr(stmt.target, "id", "변수")
            if isinstance(stmt.op, ast.Add):
                return f"{target}에 값을 누적 증가"
            elif isinstance(stmt.op, ast.Sub):
                return f"{target}에서 값을 차감 감소"
        elif isinstance(stmt, ast.Expr):
            val = stmt.value
            if isinstance(val, ast.Call):
                func_name = getattr(val.func, "id", getattr(val.func, "attr", "함수"))
                if func_name == "print":
                    return "형식에 맞추어 콘솔에 결과 출력"
                elif func_name == "append":
                    return "맨 뒤에 새 데이터 추가(push)"
                elif func_name == "pop":
                    return "맨 뒤 데이터를 꺼내어(pop) 반환"
                return f"{func_name}() 함수 실행"
            elif isinstance(val, ast.BinOp):
                if isinstance(val.op, (ast.Div, ast.FloorDiv)):
                    return "나눗셈 비율 연산 수행"
                elif isinstance(val.op, ast.Pow):
                    return "거듭제곱 연산 수행"
                elif isinstance(val.op, ast.Add):
                    return "합산 연산 수행"
            elif isinstance(val, ast.JoinedStr):
                return "요구 서식에 맞춘 f-string 문자열 포맷팅"
        elif isinstance(stmt, ast.Return):
            return "최종 계산 결과값을 반환"
        elif isinstance(stmt, ast.If):
            return "조건 일치 여부에 따라 분기 실행"
        elif isinstance(stmt, ast.For):
            return "시퀀스 원소를 순회하며 반복 실행"
        elif isinstance(stmt, ast.While):
            return "조건이 참인 동안 반복 연산 수행"
    except Exception:
        pass
    return "요구조건에 맞추어 연산 수행"


def clean_blank_answers(blanks: dict) -> list[str]:
    """빈칸 인풋창(Ghost Text) 안에 주석이 덮어써지지 않도록 순수 실행 코드만 추출합니다."""
    results = []
    for raw in blanks.values():
        clean = raw.split("#")[0].strip()
        results.append(clean)
    return results


def build_annotated_blank_template(template: str, blanks: dict) -> str:
    """빈칸 바로 윗줄에 눈에 띄는 색으로 주석(# ...)을 배치하고, 빈칸 줄에서는 주석을 분리합니다."""
    if not template:
        return ""
    lines = template.splitlines()
    raw_blanks = list(blanks.values())
    blank_idx = 0
    new_lines = []

    for line in lines:
        if "[[빈칸]]" in line:
            orig_comment = line.split("#")[1].strip() if "#" in line else ""
            clean_line = line.split("#")[0].rstrip()
            indent = clean_line[:len(clean_line) - len(clean_line.lstrip())]
            target_code = raw_blanks[blank_idx] if blank_idx < len(raw_blanks) else ""
            blank_idx += 1

            # 빈칸이 채워진 완전한 문맥 코드로 연산 의도 파악
            combined_code = clean_line.replace("[[빈칸]]", target_code.split("#")[0].strip()).strip()

            # 원본 라인 주석이 있으면 최우선 승격, 없으면 완전한 코드로부터 연산 의도 추출
            comment = orig_comment or format_inline_comment(combined_code)

            # 이전 줄이 빈 줄이 아니면 가독성을 위해 빈 줄 하나 삽입
            if new_lines and new_lines[-1].strip() != "" and not new_lines[-1].strip().startswith("#"):
                new_lines.append("")

            if comment:
                new_lines.append(f"{indent}# {comment}")
            new_lines.append(clean_line)
        else:
            new_lines.append(line)

    return "\n".join(new_lines)


def explanation(exercise):
    """답지와 해설은 카드로 따로 만들지 않고, 에디터의 윗줄 주석달기 + 회색 코드 따라쓰기로 일원화하여 처리합니다."""
    sample = exercise.tests[0]
    raw_blanks = list(exercise.blanks.values()) if exercise.kind == "blank" else []

    # 시작 코드(선언부) 줄 파악
    starter_lines = set()
    if exercise.template:
        for t_line in exercise.template.splitlines():
            clean_t = t_line.strip()
            if clean_t and "[[빈칸]]" not in clean_t and not clean_t.startswith("#"):
                starter_lines.add(clean_t)

    # 모범 코드의 각 실행 줄 윗줄에 항상 눈에 띄는 주석(# ...) 배치
    ref_lines = []
    blank_set = {b.strip().split("#")[0].strip() for b in raw_blanks}

    for line in exercise.reference.splitlines():
        trimmed = line.strip().split("#")[0].strip()
        indent = line[:len(line) - len(line.lstrip())]
        if not trimmed:
            ref_lines.append(line)
            continue

        # 시작 코드 선언 줄은 그대로 유지 (주석 달지 않음)
        if trimmed in starter_lines:
            ref_lines.append(line)
            continue

        # 빈칸 문제의 빈칸 줄이거나 본문 구현/출력 줄인 경우 윗줄 주석 배치
        comment = format_inline_comment(line.strip())
        if comment and (not ref_lines or not ref_lines[-1].strip().startswith("#")):
            if ref_lines and ref_lines[-1].strip() == "":
                ref_lines[-1] = f"{indent}# {comment}"
            else:
                ref_lines.append(f"{indent}# {comment}")
        ref_lines.append(f"{indent}{trimmed}")

    annotated_reference = "\n".join(ref_lines)

    # blanks는 빈 배열([])로 반환하여 하단의 중복 "빈칸별 답" 카드를 생성하지 않고
    # 에디터 화면의 윗줄 주석 + 회색 따라쓰기로만 깔끔하게 해설이 제공되도록 함
    return {"title": exercise.title, "kind": exercise.kind, "language": exercise.language,
            "description": exercise.prompt or "", "requirements": metadata(exercise)["requirements"],
            "reference": annotated_reference,
            "blanks": [],
            "example_input": sample["input"], "expected": sample["expected"]}
