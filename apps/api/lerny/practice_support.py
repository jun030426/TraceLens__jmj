"""Progressive practice support. No code execution and no hidden answers in views."""
import ast
import re

from sqlalchemy import select
from rag_mvp.cloze_generator import split_comment

from lerny.models import AuditEvent, PracticeAttempt, PracticeExercise, PracticeSession


def problem_attempts(student_id, section_id, *columns):
    return select(*columns).select_from(PracticeAttempt).join(PracticeExercise).where(
        PracticeAttempt.student_id == student_id, PracticeAttempt.section_id == section_id)


def first_exercise_attempts(session, student_id, section_id, problem_ids):
    """Earliest attempt per exercise. Each variant of a problem is submitted independently."""
    query = problem_attempts(student_id, section_id, PracticeAttempt)
    attempts = {}
    for attempt in session.scalars(query.where(PracticeExercise.problem_id.in_(problem_ids))
            .order_by(PracticeAttempt.created_at, PracticeAttempt.id)):
        attempts.setdefault(attempt.exercise_id, attempt)
    return attempts


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
            tests = getattr(exercise, "tests", None) or []
            statement = tests[0].get("statement") if tests else None
            requirements = ClozeGenerator.infer_dynamic_requirements(ref_code, slide_text=exercise.prompt, input_statement=statement)
        except Exception:
            pass
    tests = getattr(exercise, "tests", None) or []
    if tests and "input" not in tests[0]:
        requirements = ["빈칸 밖의 시작 코드를 유지하세요.", *requirements[1:]]

    # 가이드라인(helpers_guide_text)은 계획대로 완전히 제거하여 화면을 깔끔하게 유지
    return {"requirements": requirements, "helpers_guide_text": "",
            "available_helpers": [],
            "hint_steps": len(hints(exercise))}


def hints(exercise):
    if exercise.language == "python":
        from rag_mvp.cloze_generator import ClozeGenerator
        if exercise.kind == "blank":
            # 빈칸 채우기: 정규화된 빈칸 대상 슬롯에 집중하여 3단계 비계(목적 -> 변수/문법 도구 -> 추상 골격) 힌트 동적 생성
            norm_template, norm_blanks = normalize_blanks_and_template(exercise)
            raw_blanks = list(norm_blanks.values()) if norm_blanks else []
            code = "\n".join(raw_blanks) if raw_blanks else (exercise.reference or "")
            flow = ClozeGenerator.practice_hint_flow(exercise.title, "cloze", code)
        else:
            # 풀코딩: 전체 모범 코드(reference)를 기반으로 프로그램 구현 행동 흐름(Action Flow) 제공
            code = exercise.reference or ""
            flow = ClozeGenerator.practice_hint_flow(exercise.title, "full_coding", code)

        if not flow or not flow.get("steps"):
            flow = ClozeGenerator.generate_dynamic_action_flow(exercise.reference, title=exercise.title)
        if flow.get("steps"):
            messages = []
            for step in flow["steps"]:
                message = step["title"] + "\n" + step["action_story"]
                mnemonic = step.get("code_mnemonic")
                if mnemonic and mnemonic not in message:
                    message += "\n" + mnemonic
                messages.append(message)
            return messages

    # Non-Python or AST-incompatible languages fallback
    result = [f"「{exercise.title}」에서 주어진 입력과 구해야 하는 출력을 먼저 구분해 보세요.",
              "입력 → 처리 → 출력의 순서로 각 변수의 역할을 적어 보세요.",
              "예시 입력을 손으로 따라가며 각 단계의 값을 기록하고, 입력이 바뀌어도 같은 규칙이 적용되는지 확인하세요."]
    if exercise.kind == "full":
        result.append("입력 준비 → 필요한 상태 초기화 → 조건·반복 처리 → 결과 출력의 작은 단계로 나눠 구현하세요.")
    return result


def problem_help_events(student_id, section_id, exercise):
    return select(AuditEvent).where(AuditEvent.actor_id == student_id, AuditEvent.action == "practice_help",
        AuditEvent.target_id.in_(select(PracticeSession.id).where(PracticeSession.student_id == student_id,
            PracticeSession.section_id == section_id)),
        AuditEvent.detail["exercise_id"].as_string().in_(select(PracticeExercise.id)
            .where(PracticeExercise.problem_id == exercise.problem_id)))


def help_state(session, actor, plan, exercise):
    events = list(session.scalars(problem_help_events(actor.id, plan.section_id, exercise)))
    used = max((int(e.detail["step"]) for e in events if e.detail.get("kind") == "hint"
                and e.detail.get("exercise_id") == exercise.id and e.detail.get("step")), default=0)
    steps = hints(exercise)
    used = min(len(steps), used)
    wrong = list(session.scalars(select(PracticeAttempt.id).where(PracticeAttempt.student_id == actor.id,
        PracticeAttempt.exercise_id == exercise.id, PracticeAttempt.practice_session_id == plan.id,
        PracticeAttempt.status == "graded", PracticeAttempt.correct.is_(False))))
    attempt = session.scalar(
        select(PracticeAttempt).where(
            PracticeAttempt.student_id == actor.id,
            PracticeAttempt.section_id == plan.section_id,
            PracticeAttempt.exercise_id == exercise.id,
        ).order_by(PracticeAttempt.created_at.asc()).limit(1)
    )
    submitted_id = attempt.exercise_id if attempt else None
    return {"hints_used": used, "hints": steps[:used], "max_hint_steps": len(steps),
            "failed_attempts": len(wrong), "can_view_answer": submitted_id == exercise.id,
            "submitted_exercise_id": submitted_id, "independent": attempt.independent if attempt else not bool(events)}


def format_inline_comment(line: str) -> str:
    """코드 한 줄의 연산 의도를 분석하여 간결한 인라인 주석(# ...) 문구로 반환합니다."""
    line = line.strip()
    if not line:
        return ""
    # 원래 인라인 주석이 있으면 추출
    line, extracted_comment = split_comment(line)
    if extracted_comment:
        return extracted_comment
    if re.match(r"elif\b", line):
        return "앞선 조건이 거짓이면 다음 조건을 판별"
    if line == "else:":
        return "앞선 조건이 모두 거짓일 때 실행"

    # 특정 도메인(BMI, 사칙연산, 성적 등)에 대한 정밀 맞춤 주석
    l_lower = line.lower()
    if "height" in l_lower and ("/ 100" in line or "/100" in line):
        return "키를 100으로 나누어 미터(m) 단위로 변환"
    if "bmi" in l_lower and ("weight" in l_lower or "** 2" in line or "**2" in line):
        return "체질량지수(BMI) 공식 적용: 몸무게 / (키의 제곱)"
    if "print(" in line and ("bmi" in l_lower or ":.2f" in line):
        return "계산된 BMI 결과를 소수 둘째 자리까지 포맷팅하여 출력"
    if "total" in l_lower and "+" in line:
        return "과목 점수들을 모두 더하여 총점에 저장"
    if "avg" in l_lower and "/" in line:
        return "총점을 과목 수로 나누어 평균 계산"
    if "self.top += 1" in line:
        return "스택 최상단 포인터(top) 1 증가"
    if "self.top -= 1" in line:
        return "스택 최상단 포인터(top) 1 감소"
    if "self.rear" in line and "%" in line:
        return "큐 rear 포인터를 원형 회전 이동"

    try:
        line_to_parse = line + "\n    pass" if (line.endswith(":") and not line.endswith("pass")) else line
        tree = ast.parse(line_to_parse)
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
            test = stmt.test
            if isinstance(test, ast.BoolOp):
                return "논리 연산자(and/or)를 활용하여 복합 조건 일치 판별"
            elif isinstance(test, ast.Compare):
                return "분기 기준값과의 대소·일치 조건 비교 판별"
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
        clean = split_comment(raw)[0].strip()
        results.append(clean)
    return results


def ordered_blanks(blanks: dict) -> dict:
    """빈칸 번호는 템플릿의 [[빈칸]] 순서와 같아요. 저장소가 키 순서를 바꿔 돌려줘도 번호순으로 맞춥니다."""
    keys = list(blanks)
    if all(str(key).isdigit() for key in keys):
        keys.sort(key=lambda key: int(key))
    return {key: blanks[key] for key in keys}


def answer_key(exercise) -> list[str]:
    """제출 뒤 회색 따라쓰기로 깔아 주는 답안. 학생 화면에 보이는 템플릿과 같은 기준으로 만듭니다."""
    if exercise.kind == "blank":
        # DB 원본 blanks가 아니라, 화면의 빈칸과 같은 정규화된 빈칸의 답을 줘야 번호가 어긋나지 않아요.
        return clean_blank_answers(normalize_blanks_and_template(exercise)[1] or {})
    return [full_answer_on_template(exercise)]


def editor_reference(exercise):
    reference = exercise.reference or ""
    tests = getattr(exercise, "tests", None) or []
    if tests and (original := tests[0].get("source_statement")):
        return reference.replace(original, tests[0]["statement"], 1)
    return reference


def full_answer_on_template(exercise) -> str:
    """전체 구현 답지를 시작 코드 위에 줄을 맞춰 얹습니다.

    따라쓰기는 편집기와 답지를 같은 줄 번호끼리 겹쳐 그려요. 시작 코드의 안내 주석 줄을 그대로 두고
    그 다음 줄부터 모범 코드의 본문이 오게 해야 글자가 겹치지 않습니다.
    """
    reference = editor_reference(exercise).replace("\r\n", "\n")
    template_lines = (exercise.template or "").replace("\r\n", "\n").rstrip().split("\n")
    comment = "#" if exercise.language == "python" else "//"
    lines = reference.split("\n")
    # 시작 코드는 보통 모범 코드의 앞부분 그대로예요. 원문 맨 위의 설명 주석 줄도 여기에 들어 있어요.
    index = 0
    while (index < len(template_lines) and index < len(lines)
           and template_lines[index].rstrip() == lines[index].rstrip()):
        index += 1
    starter = [line.strip() for line in template_lines[index:]
               if line.strip() and not line.strip().startswith(comment)]
    for expected in starter:
        while index < len(lines) and (not lines[index].strip() or lines[index].strip().startswith(comment)):
            index += 1
        if index >= len(lines) or lines[index].strip() != expected:
            return reference  # 시작 코드가 모범 코드의 앞부분이 아니면 원문 그대로 둡니다.
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    body = lines[index:]
    if not any(template_lines) or not body:
        return reference
    return "\n".join(template_lines + body)


def input_lines(reference, statement):
    if not statement or statement not in reference:
        return set()
    start = reference[:reference.index(statement)].count("\n")
    return set(range(start, start + len(statement.splitlines())))


def python_blank_template(reference, selected, statement):
    """Keep valid proposed lines. Repair forbidden selections using the verified source."""
    from rag_mvp.cloze_generator import ClozeGenerator

    lines = reference.splitlines()
    protected = input_lines(reference, statement)
    chosen = sorted(i for i in set(selected) if i not in protected and not ClozeGenerator.is_excluded_line(lines[i]))
    if not chosen:
        chosen = [b["line_index"] for b in ClozeGenerator.select_blanks(reference, protected_lines=protected)]
    blanks = {}
    for i in chosen:
        line = lines[i]
        blanks[str(len(blanks) + 1)] = line.lstrip()
        lines[i] = line[:len(line) - len(line.lstrip())] + "[[빈칸]]"
    if not blanks:
        # Output-only examples can still ask for the printed expression.
        # AST columns are UTF-8 byte offsets; preserve labels, quotes and indentation.
        for i, line in enumerate(lines):
            if i in protected:
                continue
            code = line.lstrip()
            try:
                tree = ast.parse(code)
            except (SyntaxError, ValueError):
                continue
            if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Expr):
                continue
            call = tree.body[0].value
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "print"):
                continue
            arg = next((a for a in call.args if not isinstance(a, (ast.Constant, ast.Starred))), None)
            if arg is not None:
                encoded = code.encode()
                start, end = arg.col_offset, arg.end_col_offset
                blanks["1"] = encoded[start:end].decode()
                indent = line[:len(line) - len(code)]
                lines[i] = indent + encoded[:start].decode() + "[[빈칸]]" + encoded[end:].decode()
                break
    return "\n".join(lines), blanks


def normalize_blanks_and_template(exercise):
    """Repair invalid stored slots for display, keeping the saved exercise unchanged."""
    template = getattr(exercise, "template", "") or ""
    blanks = ordered_blanks(getattr(exercise, "blanks", {}) or {})
    reference = editor_reference(exercise)
    if exercise.language != "python" or exercise.kind != "blank" or not reference:
        return template, blanks
    tests = getattr(exercise, "tests", None) or []
    statement = tests[0].get("statement", "") if tests else ""
    hidden_input = statement and statement in reference and statement not in template
    forbidden = any(re.match(r"(?:print|input)\s*\(", answer.lstrip()) for answer in blanks.values())
    if hidden_input or forbidden or len(blanks) > 4:
        repaired, answers = python_blank_template(reference, (), statement)
        if answers:
            return repaired, answers
    return template, blanks


def without_python_comments(source, *, preserve=""):
    from io import StringIO
    from itertools import accumulate
    from tokenize import COMMENT, TokenError, generate_tokens

    if "#" not in source:
        return source
    lines = source.split("\n")
    offsets = list(accumulate((len(line) + 1 for line in lines), initial=0))
    start = source.find(preserve) if preserve else -1
    try:
        for token in generate_tokens(StringIO(source).readline):
            if token.type == COMMENT:
                row, col = token.start
                if start >= 0 and start <= offsets[row - 1] + col < start + len(preserve):
                    continue
                lines[row - 1] = lines[row - 1][:col].rstrip() or None
    except (IndentationError, TokenError):
        pass
    return "\n".join(line for line in lines if line is not None)


def blank_editor_templates(exercise):
    template, _ = normalize_blanks_and_template(exercise)
    if exercise.kind != "blank" or exercise.language != "python":
        return template, template
    display = without_python_comments(template)
    tests = getattr(exercise, "tests", None) or []
    statement = tests[0].get("statement", "") if tests else ""
    # The deployed grader replaces this exact, immutable input declaration for each case.
    if statement and statement in template and statement not in display:
        return without_python_comments(template, preserve=statement), display
    return display, display


def explanation(exercise):
    """답지와 해설은 카드로 따로 만들지 않고, 에디터의 윗줄 주석달기 + 회색 코드 따라쓰기로 일원화하여 처리합니다."""
    sample = exercise.tests[0] if exercise.tests else {"input": "", "expected": ""}
    norm_template, norm_blanks = normalize_blanks_and_template(exercise)
    raw_blanks = list(norm_blanks.values()) if exercise.kind == "blank" and norm_blanks else []

    # 시작 코드(선언부) 줄 파악
    starter_lines = set()
    if norm_template:
        for t_line in norm_template.splitlines():
            clean_t = t_line.strip()
            if clean_t and "[[빈칸]]" not in clean_t and not clean_t.startswith("#"):
                starter_lines.add(clean_t)

    # 모범 코드의 각 실행 줄 윗줄에 항상 눈에 띄는 주석(# ...) 배치
    ref_lines = []

    for line in (exercise.reference or "").splitlines():
        trimmed = line.strip()
        indent = line[:len(line) - len(line.lstrip())]
        if not trimmed or (exercise.language == "python" and (trimmed.startswith("#") or split_comment(line)[1])):
            ref_lines.append(line)
            continue

        # 시작 코드 선언 줄은 그대로 유지 (주석 달지 않음)
        if trimmed in starter_lines:
            ref_lines.append(line)
            continue

        # 빈칸 문제의 빈칸 줄이거나 본문 구현/출력 줄인 경우 윗줄 주석 배치
        comment = format_inline_comment(line.strip()) if exercise.language == "python" else ""
        if comment and (not ref_lines or not ref_lines[-1].strip().startswith("#")):
            if ref_lines and ref_lines[-1].strip() == "":
                ref_lines[-1] = f"{indent}# {comment}"
            else:
                ref_lines.append(f"{indent}# {comment}")
        ref_lines.append(line)

    annotated_reference = "\n".join(ref_lines)

    # 빈칸별 윗줄 주석 매핑 생성
    blank_comments = {}
    if exercise.kind == "blank" and norm_blanks:
        for k, v in norm_blanks.items():
            clean_code = split_comment(v)[0].strip()
            comment = split_comment(v)[1].strip() or format_inline_comment(clean_code)
            blank_comments[str(k)] = comment

    # 에디터 화면의 윗줄 주석 + 회색 따라쓰기로만 깔끔하게 해설이 제공되도록 함
    return {"title": exercise.title, "kind": exercise.kind, "language": exercise.language,
            "description": exercise.prompt or "", "requirements": metadata(exercise)["requirements"],
            "reference": exercise.reference, "annotated_reference": annotated_reference,
            "blanks": clean_blank_answers(norm_blanks or {}),
            "blank_comments": blank_comments,
            "example_input": sample.get("input", ""), "expected": sample["expected"]}
