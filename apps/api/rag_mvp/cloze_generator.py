"""Specialized Cloze / Blank-Filling Generator for Data Structures & Algorithms.

Analyzes Python lecture and lab code to automatically identify critical pedagogical
algorithmic and data structure points for fill-in-the-blank code practice.
"""
from __future__ import annotations
import ast
import re


def split_comment(line):
    from io import StringIO
    from tokenize import COMMENT, TokenError, generate_tokens
    try:
        for token in generate_tokens(StringIO(line).readline):
            if token.type == COMMENT:
                return line[:token.start[1]].rstrip(), token.string[1:].strip()
    except (TokenError, IndentationError):
        pass
    return line, ""


# Specialized Data Structures & Algorithms Scoring Rules
# 우선순위: 1순위 핵심 연산(100점) -> 2순위 포인터/인덱스 갱신 & 핵심 분기(90점) -> 3순위 기저/경계 방어(80점) -> 단순 삽입(75점)
# (Category, Regex Pattern, Score, Category Type)
DSA_RULES = [
    # =========================================================================
    # 1. 100점 구간: 핵심 연산 호출, 스왑, 점화식 (문제의 주인공 동작)
    # =========================================================================
    # Data Structure Primary Operation Calls (핵심 연산 호출)
    (r'(?:\w+\s*=\s*)?\w+\.pop\(\s*\)', 100, 'ds_stack_pop'),
    (r'(?:\w+\s*=\s*)?\w+\.pop\(\s*0\s*\)', 100, 'ds_queue_dequeue'),
    (r'(?:\w+\s*=\s*)?\w+\.popleft\(\s*\)', 100, 'ds_deque_popleft'),
    (r'heapq\.heappop\(.*?\)', 100, 'ds_heap_pop'),
    (r'heapq\.heappush\(.*?\)', 100, 'ds_heap_push'),

    # Algorithm Key Swaps, DP Transitions, Recursive Calls
    (r'\w+\[.*?\],\s*\w+\[.*?\]\s*=\s*\w+\[.*?\],\s*\w+\[.*?\]', 100, 'algorithm_swap'),
    (r'dp\[.*?\]\s*=\s*(?:max|min|\w+)\s*\(.*?\)', 100, 'algorithm_dp_transition'),
    (r'return\s+\w+\(.*?-\s*1\)\s*\+\s*\w+\(.*?-\s*2\)', 100, 'algorithm_recursive_call'),

    # =========================================================================
    # 2. 90점 구간: 포인터/인덱스 갱신 & 핵심 알고리즘 비교/분기
    # =========================================================================
    # Algorithm Divide & Conquer, Index/Pointer Narrowing
    (r'(?:mid|pivot_idx)\s*=\s*\(.*?\)\s*//\s*2', 90, 'algorithm_binary_search_mid'),
    (r'(?:low|left)\s*=\s*mid\s*\+\s*1', 90, 'algorithm_binary_search_pointer'),
    (r'(?:high|right)\s*=\s*mid\s*-\s*1', 90, 'algorithm_binary_search_pointer'),
    (r'mid\s*=\s*len\(\w+\)\s*//\s*2', 90, 'algorithm_merge_sort_split'),

    # Data Structure Pointer Mutation & Link Rewiring
    (r'self\.(?:top|front|rear)\s*(?:\+=|-=)\s*1', 90, 'ds_pointer_mutation'),
    (r'self\.(?:front|rear)\s*=\s*\(.*?\)\s*%\s*\w+', 90, 'ds_circular_queue_advance'),
    (r'(?:new_node|node)\.next\s*=\s*(?:self\.)?head', 90, 'ds_linked_list_insert_front'),
    (r'(?:self\.)?head\s*=\s*(?:new_node|node)', 90, 'ds_linked_list_head_update'),
    (r'curr\s*=\s*curr\.next', 90, 'ds_linked_list_traverse'),

    # Specific Algorithm Key Branching
    (r'if\s+\w+\[j\]\s*>\s*\w+\[j\s*\+\s*1\]\s*:', 90, 'algorithm_bubble_sort_cmp'),
    (r'if\s+target\s*(?:==|<|>)\s*\w+\[mid\]\s*:', 90, 'algorithm_binary_search_cmp'),
    (r'if\s+\w+\[mid\]\s*(?:==|<|>)\s*target\s*:', 90, 'algorithm_binary_search_cmp'),
    (r'elif\s+arr\[mid\]\s*<\s*target\s*:', 90, 'algorithm_binary_search_cmp'),
    (r'if\s+.*?(?:and|or|not)\s+.*?:', 90, 'logical_condition'),
    (r'elif\s+.*?(?:and|or|not)\s+.*?:', 90, 'logical_condition'),
    (r'if\s+(?:cost|new_dist|d)\s*<\s*(?:distance|dist)\[.*?\]\s*:', 90, 'algorithm_dijkstra_relaxation'),
    (r'if\s+\w+\s+(?:not\s+in|in)\s+visited\s*:', 90, 'algorithm_visited_check'),

    # =========================================================================
    # 3. 80점 구간: 기저 조건(Base Case) 및 자료구조 경계 방어 (안전장치)
    # =========================================================================
    # Data Structure Boundary & State Checks (언더플로우/오버플로우/공백/포화)
    (r'if\s+(?:len\(\w+\)\s*(?:<=|==)\s*0|not\s+\w+|\w+\.is_empty\(\)|self\.top\s*==\s*-1|self\.top\s*<\s*0)', 80, 'ds_underflow_check'),
    (r'if\s+len\(\w+\)\s*>\s*0\s*:', 80, 'ds_underflow_check'),
    (r'if\s+(?:len\(\w+\)\s*(?:>=|==)\s*(?:self\.)?capacity|\w+\.is_full\(\)|self\.top\s*(?:>=|==)\s*(?:self\.)?capacity\s*-\s*1)', 80, 'ds_overflow_check'),
    (r'if\s+\(.*?rear\s*\+\s*1\)\s*%\s*\w+\s*==\s*.*?front', 80, 'ds_circular_queue_full_check'),

    # Algorithm Base Cases (탈출 조건)
    (r'if\s+(?:n|depth|cnt|count|k)\s*(?:<=|==)\s*(?:0|1|\w+)\s*:', 80, 'algorithm_base_case'),
    (r'if\s+(?:low|start|left)\s*>\s*(?:high|end|right)\s*:', 80, 'algorithm_base_case'),
    (r'if\s+(?:not\s+(?:node|root|curr|head)|(?:node|root|curr|head)\s+is\s+None)\s*:', 80, 'algorithm_base_case'),
    (r'while\s+(?:low|left|start)\s*<=\s*(?:high|right|end)\s*:', 80, 'algorithm_loop_invariant'),

    # General Conditions (일반 조건문 분기)
    (r'if\s+.*?(?:<=|>=|<|>|==|!=).*?:', 80, 'conditional_branch'),
    (r'elif\s+.*?(?:<=|>=|<|>|==|!=).*?:', 80, 'conditional_branch'),

    # =========================================================================
    # 4. 75점 구간: 단순 데이터 추가 (append)
    # =========================================================================
    (r'\w+\.append\(.*?\)', 75, 'ds_push_or_enqueue')
]

# Exclusion Blacklist Patterns (Do NOT blank these lines)
EXCLUSION_PATTERNS = [
    r'\bprint\s*\(',
    r'\binput\s*\(',
    r'^\s*if\s+(?:menu|choice|cmd|command)\s*==',
    r'^\s*while\s+True\s*:',
    r'^\s*break\s*$',
    r'^\s*continue\s*$',
    r'^\s*import\s+',
    r'^\s*from\s+',
    r'^\s*pass\s*$',
    r'^\s*class\s+',
    r'^\s*(?:async\s+)?def\s+'
]


class ClozeGenerator:
    """Automated Blank Selection & Cloze Problem Generator for DS & Algorithms."""

    @staticmethod
    def is_excluded_line(line):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            return True
        for pattern in EXCLUSION_PATTERNS:
            if re.search(pattern, stripped):
                return True
        return False

    @classmethod
    def score_line(cls, line):
        """Calculate DSA pedagogical score for a line of code."""
        if cls.is_excluded_line(line):
            return 0, None

        stripped = line.strip()

        # Explicit instructor override
        if '# [blank]' in stripped.lower():
            return 200, 'instructor_manual_override'

        for pattern, score, category in DSA_RULES:
            if re.search(pattern, stripped):
                return score, category

        return 0, None

    @classmethod
    def select_blanks(cls, code, min_score=80, max_blanks=4, *, protected_lines=()):
        """Select top critical lines from code as cloze blanks (at most half of code lines)."""
        lines = code.splitlines()
        code_lines = sum(1 for line in lines if line.strip() and not line.strip().startswith('#'))
        effective_max = max(1, min(max_blanks, code_lines // 2)) if code_lines else max_blanks
        candidates = []
        for idx, line in enumerate(lines):
            if idx in protected_lines or cls.is_excluded_line(line):
                continue
            score, category = cls.score_line(line)
            if not score:
                stripped = line.strip()
                parse_target = stripped + "\n    pass" if stripped.endswith(":") else stripped
                try:
                    stmt = ast.parse(parse_target).body[0]
                except (SyntaxError, IndexError, ValueError):
                    continue
                if isinstance(stmt, ast.Return) and stmt.value is not None:
                    if isinstance(stmt.value, (ast.BinOp, ast.Call, ast.Compare, ast.BoolOp, ast.IfExp, ast.Subscript, ast.UnaryOp)):
                        score, category = 65, "return_expression"
                    else:
                        score, category = 55, "return_value"
                elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                    score, category = 65, "loop_control"
                elif isinstance(stmt, ast.AugAssign):
                    score, category = 60, "calculation"
                elif (isinstance(stmt, (ast.Assign, ast.AnnAssign))
                      and isinstance(stmt.value, (ast.BinOp, ast.Call, ast.Compare, ast.BoolOp, ast.IfExp, ast.Subscript))):
                    score, category = 60, "calculation"
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    score, category = 60, "function_call"
                else:
                    continue
            candidates.append({"line_index": idx, "line_no": idx + 1, "raw_line": line,
                               "answer": line.strip(), "indentation": line[:len(line) - len(line.lstrip())],
                               "score": score, "category": category})

        for threshold in (min_score, 70, 60, 55):
            eligible = [candidate for candidate in candidates if candidate["score"] >= threshold]
            if eligible:
                candidates = eligible
                break

        # Sort by score descending, then line order ascending
        candidates.sort(key=lambda x: (-x['score'], x['line_no']))

        # Ensure blanks are not on consecutive lines if possible
        chosen = []
        chosen_line_indices = set()
        for cand in candidates:
            idx = cand['line_index']
            # Allow at most effective_max (never blank more than half the code lines)
            if len(chosen) >= effective_max:
                break
            # Prefer non-adjacent lines for readability
            if len(candidates) > effective_max and any(abs(idx - c_idx) <= 1 for c_idx in chosen_line_indices):
                continue
            chosen.append(cand)
            chosen_line_indices.add(idx)

        # If not enough non-adjacent candidates, take next highest
        if len(chosen) < min(effective_max, len(candidates)):
            for cand in candidates:
                if len(chosen) >= effective_max:
                    break
                if cand['line_index'] not in chosen_line_indices:
                    chosen.append(cand)
                    chosen_line_indices.add(cand['line_index'])

        # Re-sort chosen blanks by line order
        chosen.sort(key=lambda x: x['line_no'])

        labels = ['(가)', '(나)', '(다)', '(라)']
        for i, b in enumerate(chosen):
            b['label'] = labels[i] if i < len(labels) else f"({i+1})"

        return chosen

    @classmethod
    def resolve_domain_formula_requirement(cls, code: str, combined_text: str = "", slide_text: str = "") -> str:
        """Describe the requested quantity and units without transcribing the reference expression."""
        topic = (combined_text + " " + (slide_text or "")).lower()
        if "bmi" in topic or "체질량" in topic:
            return "키와 체중의 단위를 확인한 뒤 체질량지수를 계산하세요."
        if any(word in topic for word in ("섭씨", "화씨", "celsius", "fahrenheit")):
            return "시작 온도의 단위를 확인하고 문제에서 요구한 단위로 변환하세요."
        if any(word in topic for word in ("할인", "discount")):
            return "주어진 할인 조건을 적용해 최종 결제 금액을 구하세요."
        if any(word in topic for word in ("세금", "부가세", "세율")):
            return "주어진 세율과 금액 단위를 확인해 요구한 금액을 구하세요."
        if any(word in topic for word in ("넓이", "둘레", "부피", "피타고라스")):
            return "주어진 길이의 단위를 확인하고 문제에서 요구하는 도형의 값을 구하세요."
        if "시간 환산" in topic or "시간 변환" in topic:
            return "주어진 시간을 문제에서 요구한 단위와 순서로 나타내세요."
        return ""

    @classmethod
    def infer_dynamic_requirements(cls, code: str, slide_text: str = None, *, input_statement: str | None = None) -> list[str]:
        """임의의 어떤 파이썬 코드가 주어지더라도 AST 구문 분석을 통해
        [1. 입력 선언 유지 -> 2. 도메인별 핵심 연산 정합화 -> 3. 출력/반환 서식 준수]
        의 3단계 표준 문제 요구조건을 정답 코드 노출(스포일러) 없이 동적으로 자동 생성합니다."""
        if not code or not code.strip():
            return [
                "시작 코드의 입력 변수 선언을 유지하세요.",
                "문제에서 요구한 핵심 연산 및 처리 순서를 준수하세요.",
                "출력 결과는 예시 출력 서식과 소수점 자릿수를 정확히 준수하세요."
            ]

        reqs = []
        prefix = slide_text if slide_text else ""
        combined_text = (prefix + "\n" + code).lower()

        # 1. 입력 변수 및 함수 매개변수 동적 감지
        try:
            body = ast.parse(code).body
        except (SyntaxError, ValueError):
            body = []
        input_vars, assign_targets, func_params = [], [], []
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_params = [arg.arg for arg in node.args.args if arg.arg != "self"]
            elif isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "input"
                       for child in ast.walk(node.value)):
                    input_vars.extend(targets)
                elif not isinstance(node.value, (ast.Constant, ast.List, ast.Tuple, ast.Dict)):
                    assign_targets.extend(targets)
        if input_statement:
            try:
                declared = ast.parse(input_statement)
                input_vars = [node.id for node in ast.walk(declared)
                              if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)]
            except (SyntaxError, ValueError):
                input_vars = []
        input_vars = list(dict.fromkeys(input_vars))
        assign_targets = list(dict.fromkeys(assign_targets))
        if func_params and not input_statement:
            reqs.append("함수의 입력 매개변수(" + ", ".join(func_params[:3]) + ")와 전달 인자 조건을 유지하세요.")
        elif input_vars:
            reqs.append("시작 코드의 입력 변수(" + ", ".join(input_vars[:3]) + ") 선언을 유지하세요.")
        else:
            reqs.append("시작 코드의 입력 변수 선언 및 초기화 상태를 유지하세요.")

        # 2. 도메인별 상식 공식 및 핵심 연산 패턴 동적 감지
        # 안내에는 목표와 단위를 쓰고 모범 코드의 식은 공개하지 않는다.
        formula_req = cls.resolve_domain_formula_requirement(code, combined_text=combined_text, slide_text=slide_text)

        has_unit_scaling = bool(
            re.search(r"/\s*100\b", code) or re.search(r"\*\s*1000\b", code) or
            "cm" in combined_text or "센티미터" in combined_text or "미터" in combined_text or
            ("height" in combined_text and "weight" in combined_text) or "단위" in combined_text
        )
        has_average = any(word in combined_text for word in ("평균", "average", "mean", "avg"))
        has_arithmetic = bool(
            all(op in code for op in ("+", "-", "*")) or "사칙연산" in combined_text or
            ("덧셈" in combined_text and "나눗셈" in combined_text)
        )
        has_pow_formula = bool("**" in code or "bmi" in combined_text or "^" in combined_text)
        has_mod_parity = bool("% 2" in code or "짝수" in combined_text or "홀수" in combined_text)
        has_condition = bool("if " in code)
        has_search_sort = bool(
            "binary_search" in combined_text or "sort" in combined_text or
            re.search(r"while\s+\w+\s*<=\s*\w+", code) or "이진" in combined_text or "정렬" in combined_text
        )
        has_dsa = bool(
            any(k in combined_text for k in ("stack", "queue", "pop", "push", "top", "rear", "front", "dequeue", "enqueue"))
        )
        has_string_ops = bool(
            "len(" in code and ("str" in combined_text or "text" in combined_text or "@" in combined_text or "email" in combined_text)
        )

        if formula_req:
            reqs.append(formula_req)
        elif has_search_sort:
            reqs.append("탐색/정렬의 범위 갱신과 반복 종료(기저) 조건을 엄격히 준수하여 알고리즘을 완성하세요.")
        elif has_dsa:
            reqs.append("자료구조의 기저/경계 조건(언더플로우·오버플로우)을 방어하고 포인터 상태를 안전하게 갱신하세요.")
        elif has_average:
            reqs.append("대상 값과 개수를 확인해 문제에서 요구한 평균을 구하세요.")
        elif has_arithmetic:
            reqs.append("두 수에 대한 각 사칙연산(덧셈: +, 뺄셈: -, 곱셈: *, 나눗셈: /) 결과를 각각 도출하세요.")
        elif has_unit_scaling:
            reqs.append("입력 데이터의 단위 체계를 공식 및 요구조건에 맞추어 적절히 환산·정합화하세요.")
        elif has_pow_formula:
            reqs.append("문제에서 요구한 연산 우선순위와 거듭제곱(**) 및 나눗셈 비율을 올바르게 적용하세요.")
        elif has_mod_parity:
            reqs.append("입력값의 홀짝에 따라 요구한 결과를 구분하세요.")
        elif has_string_ops:
            reqs.append("문자열 길이(len) 및 특정 문자 패턴 포함 여부를 올바르게 검사하세요.")
        elif has_condition:
            reqs.append("문제에서 요구한 분기 기준값과의 대소·일치 조건을 올바르게 비교 판별하세요.")
        else:
            # 규칙 기반 깡통 문장을 영구 퇴출하고 교안 지문(slide_text) 및 타깃 변수(assign_targets)를 분석하여 자연스러운 도메인 문장 동적 생성
            inferred_action = ""
            if slide_text and slide_text.strip():
                clean_slide = slide_text.strip().split("\n")[0].split(".")[0].strip()
                # 지문에서 핵심 변환/계산 목표 추출 (예: '섭씨(celsius) 온도를 입력받아 화씨(fahrenheit) 온도로 변환하여 출력합니다.')
                m = re.search(r"(?:입력받아|주어졌을\s*때|활용하여)\s*(.+?)(?:하여\s*출력|하고\s*출력|출력합니다|구합니다|$)", clean_slide)
                if m:
                    candidate = m.group(1).strip()
                    if candidate.endswith(("변환", "계산", "산출", "도출", "판별")):
                        inferred_action = f"{candidate}하는 공식을 올바르게 적용하세요."
                    elif candidate.endswith("로"):
                        inferred_action = f"{candidate} 변환하는 공식을 올바르게 적용하세요."
                    elif "온도" in candidate:
                        inferred_action = f"{candidate} 변환 처리를 올바르게 구현하세요."
                    else:
                        inferred_action = f"{candidate} 연산을 올바르게 구현하세요."

            if not inferred_action:
                if assign_targets and input_vars:
                    inferred_action = f"입력 변수({', '.join(input_vars[:2])})를 바탕으로 '{', '.join(assign_targets[:2])}' 변수의 계산 공식을 올바르게 적용하세요."
                elif assign_targets:
                    inferred_action = f"연산식을 완성하여 '{', '.join(assign_targets[:2])}' 변수에 올바른 결괏값을 도출하세요."
                else:
                    inferred_action = "주어진 입력 데이터를 바탕으로 요구된 연산 및 로직을 순서대로 올바르게 구현하세요."

            reqs.append(inferred_action)

        # 3. 출력 및 반환 서식 동적 감지
        has_print = "print(" in code
        has_return = "return " in code
        has_float_fmt = bool(":.2f" in code or ":.1f" in code or "round(" in code or (has_unit_scaling and "bmi" in combined_text))
        has_colon_label = bool(re.search(r"print\([^)]*[:：]", code))

        if has_print:
            if has_float_fmt:
                reqs.append("출력 결과는 예시 출력 서식과 소수점 자릿수를 정확히 준수하세요.")
            elif has_colon_label:
                reqs.append("출력 형식의 라벨 문자열, 콜론(:), 공백 구분을 예시 출력과 정확히 일치시키세요.")
            else:
                reqs.append("요구된 예시 출력 형식에 맞추어 콘솔에 결과를 정확히 출력하세요.")
        elif has_return:
            reqs.append("계산된 최종 결괏값을 함수의 반환 규격(자료형 및 값)에 맞추어 return하세요.")
        else:
            reqs.append("최종 결과가 문제의 요구 형식과 일치하도록 완성하세요.")

        return reqs

    @classmethod
    def infer_problem_statement(cls, code: str, title: str = None, description: str = None,
                                requirements: list = None, slide_text: str = None, concept_id: str = None) -> dict:
        """교안 슬라이드 텍스트 및 AST 함수 분석을 통해 실습 문제의 [제목, 글 지문, 요구조건]을 자동 생성합니다."""
        if title and description:
            return {
                'title': title,
                'description': description,
                'requirements': requirements or []
            }

        inferred_func = None
        docstring = None
        try:
            tree = ast.parse(code)
            funcs = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            # __init__ 등 보일러플레이트를 제외하고 핵심 DSA 함수 우선 탐색
            non_init = [f for f in funcs if f.name != '__init__']
            if non_init:
                best_f = None
                best_score = -1
                lines = code.splitlines()
                for f in non_init:
                    end_ln = getattr(f, 'end_lineno', f.lineno)
                    score = max((cls.score_line(lines[i])[0] for i in range(f.lineno - 1, min(end_ln, len(lines)))), default=0)
                    if score > best_score:
                        best_score = score
                        best_f = f
                target_node = best_f or non_init[0]
            else:
                target_node = funcs[0] if funcs else None

            if target_node:
                inferred_func = target_node.name
                ds = ast.get_docstring(target_node)
                if ds and not docstring:
                    docstring = ds.strip()
        except Exception:
            pass

        templates = {
            'pop': {
                'title': '스택의 pop() 연산 구현하기',
                'description': '스택(Stack)의 최상단(Top) 데이터를 꺼내어 반환하는 pop() 메서드입니다. 스택이 비어있는 언더플로우 조건을 방어하고, 최상단 원소를 안전하게 추출하여 반환하도록 빈칸을 채우세요.',
                'requirements': [
                    '스택이 비어있는 경우(Underflow)를 확인하여 None을 반환해야 합니다.',
                    '최상단(Top) 원소를 추출하고 포인터 위치를 올바르게 갱신해야 합니다.'
                ]
            },
            'push': {
                'title': '스택의 push() 연산 구현하기',
                'description': '스택(Stack)의 최상단(Top)에 새로운 데이터를 삽입하는 push() 메서드입니다. 스택 포화(Overflow) 여부를 확인하고 정상적으로 새 원소를 저장하도록 빈칸을 채우세요.',
                'requirements': [
                    '스택이 가득 찬 경우(Overflow)를 점검해야 합니다.',
                    'Top 위치를 갱신하여 새 데이터를 올바른 위치에 저장해야 합니다.'
                ]
            },
            'peek': {
                'title': '스택의 peek() 연산 구현하기',
                'description': '스택(Stack)의 맨 위(Top) 원소를 삭제하지 않고 조회하는 peek() 메서드입니다.',
                'requirements': [
                    '원소를 삭제하거나 Top 포인터를 변경하지 않고 데이터만 반환해야 합니다.'
                ]
            },
            'enqueue': {
                'title': '큐의 enqueue() 연산 구현하기',
                'description': '큐(Queue)의 끝(Rear)에 새로운 데이터를 추가하는 enqueue() 메서드입니다. 큐 포화 상태를 확인하고 새 원소를 삽입하도록 빈칸을 채우세요.',
                'requirements': [
                    '큐가 포화 상태인지 확인하고, Rear 위치를 전진시켜 데이터를 삽입해야 합니다.'
                ]
            },
            'dequeue': {
                'title': '큐의 dequeue() 연산 구현하기',
                'description': '큐(Queue)의 앞(Front)에서 데이터를 꺼내어 반환하는 dequeue() 메서드입니다. 큐가 비어있는지 확인하고 Front 데이터를 반환하도록 빈칸을 채우세요.',
                'requirements': [
                    '큐가 비어있는 언더플로우 상태를 확인해야 합니다.',
                    'Front 데이터를 안전하게 추출하고 위치를 갱신해야 합니다.'
                ]
            },
            'binary_search': {
                'title': '이진 탐색(Binary Search) 알고리즘 구현하기',
                'description': '정렬된 배열에서 타깃 값을 O(log n)의 시간복잡도로 탐색하는 이진 탐색 함수입니다. 중간값(mid)과의 대소 비교를 통해 탐색 범위를 절반씩 좁혀나가도록 빈칸을 채우세요.',
                'requirements': [
                    '탐색 범위를 결정하는 기저 조건(low <= high)을 올바르게 설정해야 합니다.',
                    '타깃과의 비교 결과에 따라 low 또는 high 포인터를 갱신해야 합니다.'
                ]
            },
            'bmi': {
                'title': 'BMI 계산 프로그램 구현하기',
                'description': '키(height)와 몸무게(weight)를 입력받아 체질량지수를 구하는 BMI 계산 공식 [BMI = 몸무게(kg) / (키(m))²]을 적용하고 소수점 둘째 자리까지 출력하는 프로그램입니다. (단, 입력된 키의 단위(cm)를 100으로 나누어 미터(m) 단위로 환산해야 합니다.)',
                'requirements': [
                    '시작 코드의 입력 변수 선언을 유지하세요.',
                    '키(cm)를 미터(m) 단위로 환산한 뒤, 공식 [BMI = 몸무게(kg) / (키(m))²]을 적용하여 계산하세요.',
                    '출력 결과는 예시 출력 서식과 소수점 자릿수를 정확히 준수하세요.'
                ]
            },
            'arithmetic': {
                'title': '사칙연산 프로그램 구현하기',
                'description': '두 수(a, b)를 입력받아 덧셈, 뺄셈, 곱셈, 나눗셈 결과를 각각 계산하고 형식에 맞춰 출력하는 프로그램입니다.',
                'requirements': [
                    '시작 코드의 입력 변수 선언을 유지하세요.',
                    '두 수의 사칙연산(덧셈, 뺄셈, 곱셈, 나눗셈 실수)을 각각 계산하세요.',
                    '출력 형식의 콜론(:)과 공백을 예시 출력과 동일하게 맞추세요.'
                ]
            },
            'email': {
                'title': '이메일 유효성 및 문자열 분석 프로그램',
                'description': '이메일 주소 문자열을 분석하여 특수문자(@)의 포함 여부와 전체 길이를 확인하는 프로그램입니다.',
                'requirements': [
                    '시작 코드의 입력 변수 선언을 유지하세요.',
                    '문자열의 길이(len)와 특수문자(@) 포함 여부를 올바르게 판별하세요.',
                    '출력 결과는 예시 출력 서식과 정확히 일치시키세요.'
                ]
            },
            'average': {
                'title': '성적 합계 및 평균 계산 프로그램',
                'description': '여러 점수의 합계와 평균을 계산하여 출력하는 프로그램입니다.',
                'requirements': [
                    '시작 코드의 입력 변수 선언을 유지하세요.',
                    '모든 점수의 합계를 누적 합산하고, 이를 과목 수로 나누어 평균을 계산하세요.',
                    '출력 결과는 예시 출력 서식과 소수점 자릿수를 정확히 준수하세요.'
                ]
            }
        }

        matched = None
        combined_probe = f"{concept_id or ''} {inferred_func or ''} {code} {slide_text or ''}".lower()
        if concept_id:
            for k in templates:
                if k in concept_id.lower():
                    matched = templates[k]
                    break
        if not matched and inferred_func:
            for k in templates:
                if k in inferred_func.lower():
                    matched = templates[k]
                    break
        if not matched:
            if 'bmi' in combined_probe or ('height' in combined_probe and 'weight' in combined_probe):
                matched = templates['bmi']
            elif '사칙연산' in combined_probe or ('덧셈' in combined_probe and '나눗셈' in combined_probe):
                matched = templates['arithmetic']
            elif '이메일' in combined_probe or 'email' in combined_probe or ('len(' in combined_probe and '@' in combined_probe):
                matched = templates['email']
            elif '평균' in combined_probe or 'average' in combined_probe:
                matched = templates['average']

        if matched:
            t = title or matched['title']
            d = description or (docstring if docstring else matched['description'])
            r = requirements if requirements is not None else matched['requirements']
            return {'title': t, 'description': d, 'requirements': r}

        gen_title = title or (f'[{inferred_func}] 실습 알고리즘 완성하기' if inferred_func else '실습 알고리즘 빈칸 완성하기')
        if docstring:
            gen_desc = docstring
        elif slide_text and len(slide_text.strip()) > 10:
            lines = [l.strip() for l in slide_text.splitlines() if l.strip()]
            gen_desc = ' '.join(lines[:2])
        else:
            gen_desc = '제시된 코드의 핵심 알고리즘 로직이 정상 작동하도록 요구사항에 맞게 빈칸을 채우시오.'

        gen_reqs = requirements if requirements is not None else cls.infer_dynamic_requirements(code, slide_text=slide_text)

        return {'title': gen_title, 'description': gen_desc, 'requirements': gen_reqs}

    @classmethod
    def generate_practice_statement(cls, code: str, client=None, slide_text: str = None,
                                    concept_id: str = None, title: str = None,
                                    description: str = None, requirements: list = None) -> dict:
        """교안 슬라이드와 코드로부터 실습 문제 지문(제목, 문제 설명, 요구조건)을 생성합니다.

        우선순위(Hierarchy):
        - 0순위: 사용자 명시 지정 (title, description이 직접 제공된 경우 즉시 반환)
        - 1순위: Gemini AI를 활용한 교수님 실습 문맥 맞춤형 지문 자동 생성 (client 제공 시)
        - 2순위: AST 분석 및 정적 DSA 규칙 템플릿 Fallback (Gemini API 실패, 타임아웃, 오프라인 시 무중단 전환)
        """
        if title and description:
            return {
                'title': title,
                'description': description,
                'requirements': requirements or [],
                'source': 'manual_override'
            }

        # 1순위: Gemini AI 호출 시도
        if client is not None:
            try:
                from video_extraction.shared.gemini import obj, TEXT, STRINGS
                from quiz_mvp.generation import call_json

                step_schema = obj({
                    'step_number': {'type': 'integer'},
                    'title': TEXT,
                    'action_story': TEXT,
                    'code_mnemonic': TEXT
                })
                statement_schema = obj({
                    'title': TEXT,
                    'description': TEXT,
                    'requirements': STRINGS,
                    'flow_steps': {'type': 'array', 'items': step_schema}
                })

                system_prompt = (
                    "You are an expert Computer Science professor assistant creating a practice coding problem statement "
                    "from real lecture and lab code. Given the code and optional slide context/concept, generate a clear, "
                    "engaging, student-friendly problem statement in Korean.\n\n"
                    "Strict Requirements:\n"
                    "1. title: Clear and concise problem title (e.g. '[스택] pop() 메서드 구현하기', 'BMI 계산 프로그램', '사칙연산 프로그램')\n"
                    "2. description: Engaging explanation of the function/algorithm's purpose, rationale, and expected behavior (2~3 sentences).\n"
                    "   * CRITICAL FORMULA & UNIT RULE: If the slide text, code, or comments contain mathematical formulas (e.g., BMI = weight / (height ** 2), average = total / count) "
                    "     or required unit conversions (e.g., convert cm to m by dividing height by 100), you MUST explicitly include the exact calculation formula and unit conversion in the description!\n"
                    "3. requirements: List of 2~3 concrete technical requirements.\n"
                    "   * MANDATORY FORMULA IN REQUIREMENTS: If the problem requires any domain/mathematical formula or unit conversion, "
                    "     you MUST explicitly write the formula in requirements (e.g., '공식 [결과 = 수식]을 적용하여 계산하세요.') "
                    "     so students do not need to memorize external formulas or rely on hints!\n"
                    "4. flow_steps: Exactly 3 logical step-by-step problem-solving actions for student guidance "
                    "   (Step 1: unit conversion or input prep, Step 2: core calculation/formula, Step 3: formatting and output).\n"
                    "Return valid JSON matching the schema."
                )

                payload = {
                    'code': code,
                    'concept_id': concept_id or '',
                    'slide_text': slide_text or ''
                }

                if hasattr(client, 'request') and hasattr(client, 'answer_model'):
                    parsed = call_json(client, 'practice_statement_v1', system_prompt, payload, statement_schema)
                elif callable(getattr(client, 'generate_practice_statement', None)):
                    parsed = client.generate_practice_statement(code=code, slide_text=slide_text, concept_id=concept_id)
                elif callable(client):
                    parsed = client(payload)
                else:
                    parsed = None

                if parsed and parsed.get('title') and parsed.get('description'):
                    reqs = parsed.get('requirements') or []
                    if isinstance(reqs, str):
                        reqs = [reqs]
                    cleaned_reqs = [str(r).strip() for r in reqs if str(r).strip()]
                    return {
                        'title': str(parsed['title']).strip(),
                        'description': str(parsed['description']).strip(),
                        'requirements': cleaned_reqs or ['알고리즘 입출력 및 제약 조건을 준수하세요.'],
                        'flow_steps': parsed.get('flow_steps') or [],
                        'source': 'gemini'
                    }
            except Exception:
                # Gemini 호출 실패(네트워크, 쿼터, 파싱 오류 등) 시 무중단으로 2순위 Fallback 전환
                pass

        # 2순위: AST 분석 및 정적 DSA 규칙 템플릿 Fallback
        fallback_res = cls.infer_problem_statement(
            code=code,
            title=title,
            description=description,
            requirements=requirements,
            slide_text=slide_text,
            concept_id=concept_id
        )
        fallback_res['source'] = 'rule_fallback'
        return fallback_res

    @classmethod
    def generate_cloze_problem(cls, code, min_score=80, max_blanks=2,
                               title=None, description=None, requirements=None,
                               slide_text=None, concept_id=None, client=None):
        """Generate masked code and blank metadata for student practice with rich problem description."""
        blanks = cls.select_blanks(code, min_score=min_score, max_blanks=max_blanks)
        lines = code.splitlines()

        blank_by_index = {b['line_index']: b for b in blanks}
        masked_lines = []

        for idx, line in enumerate(lines):
            if idx in blank_by_index:
                b = blank_by_index[idx]
                masked_lines.append(f"{b['indentation']}[ {b['label']} ____________________________ ]")
            else:
                masked_lines.append(line)

        problem_meta = cls.generate_practice_statement(
            code=code,
            client=client,
            title=title,
            description=description,
            requirements=requirements,
            slide_text=slide_text,
            concept_id=concept_id
        )

        helper_meta = cls.extract_available_helpers(code, slide_text=slide_text)

        return {
            'title': problem_meta['title'],
            'description': problem_meta['description'],
            'requirements': problem_meta['requirements'],
            'available_helpers': helper_meta['available_helpers'],
            'helpers_guide_text': helper_meta['helpers_guide_text'],
            'flow_steps': problem_meta.get('flow_steps', []),
            'statement_source': problem_meta.get('source', 'rule_fallback'),
            'original_code': code,
            'masked_code': '\n'.join(masked_lines),
            'blanks': blanks,
            'blank_count': len(blanks)
        }

    COMMON_DSA_ATTR_DESCS = {
        'items': '스택/큐 원소들이 저장된 리스트',
        'top': '스택 최상단 원소의 인덱스 포인터 (비어있을 시 -1)',
        'capacity': '스택/큐의 최대 저장 용량',
        'front': '큐 맨 앞 원소의 인덱스 포인터',
        'rear': '큐 맨 뒤 원소의 인덱스 포인터',
        'head': '연결 리스트의 첫 번째 노드 포인터',
        'tail': '연결 리스트의 마지막 노드 포인터',
        'size': '현재 저장된 원소의 총 개수',
        'max_size': '자료구조의 최대 허용 크기',
        'data': '노드 또는 버퍼에 저장된 데이터 값',
        'next': '다음 노드를 가리키는 포인터'
    }

    COMMON_DSA_FUNC_DESCS = {
        'is_empty': '스택/큐가 비어있는지 확인 (True / False 반환)',
        'is_full': '스택/큐가 가득 찼는지 확인 (True / False 반환)',
        'peek': '최상단 원소를 삭제하지 않고 조회 반환',
        'size': '현재 저장된 원소 개수 반환',
        'get_size': '현재 저장된 원소 개수 반환',
        'clear': '모든 원소를 초기화하고 비움',
        'display': '현재 저장된 원소들을 화면에 출력'
    }

    @classmethod
    def extract_available_helpers(cls, code: str, target_func_name: str = None, slide_text: str = None) -> dict:
        """클래스 코드 내 헤더/보조 함수뿐만 아니라 일반 절차형 스크립트의 내장 함수, 연산자,
        슬라이드 내 수학 공식까지 감지하여 실습 안내 가이드라인을 생성합니다."""
        helpers = []
        guide_lines = []

        # 1. 슬라이드 본문 및 주석에서 핵심 계산 공식 추출 (예: BMI, 총점, 평균 등)
        combined_text = f"{slide_text or ''}\n{code or ''}"
        # Keep balanced parentheses in formulas, including those embedded in slide prose.
        formula_matches = []
        for match in re.finditer(r'(\b[A-Za-z가-힣_]\w*\s*=\s*)([^,\n#]+)', combined_text):
            expression = match[2]
            depth = 0
            for i, char in enumerate(expression):
                if char == '(':
                    depth += 1
                elif char == ')':
                    if depth == 0:
                        expression = expression[:i]
                        break
                    depth -= 1
            formula_matches.append(match[1] + expression)
        found_formulas = []
        for f in formula_matches:
            f_clean = f.strip()
            if any(k in f_clean for k in ['BMI', 'bmi', '총점', '평균', 'average', 'total', '/', '*', '**', '+', '-']):
                if f_clean not in found_formulas and len(f_clean) > 4:
                    found_formulas.append(f_clean)
                    guide_lines.append(f"• 핵심 계산 공식: `{f_clean}`")

        # 단위 변환 힌트 (예: cm -> m)
        if ('cm' in combined_text.lower() or '센티미터' in combined_text) and (
                re.search(r'/\s*100\b', code) or '미터' in combined_text or '키(m)' in combined_text):
            guide_lines.append("• 단위 변환 주의: cm 단위 입력값은 공식 대입 전 100으로 나누어 미터(m) 단위로 변환해야 합니다.")

        # 2. 코드 내 사용된 파이썬 내장 도구 및 특수 연산자 감지
        if "**" in code:
            helpers.append({'kind': 'operator', 'name': '**', 'description': '거듭제곱 연산자 (예: height ** 2)'})
        if "/" in code:
            helpers.append({'kind': 'operator', 'name': '/', 'description': '나눗셈 연산자 (결과값은 float 실수)'})
        if "//" in code:
            helpers.append({'kind': 'operator', 'name': '//', 'description': '정수 나눗셈 몫 연산자'})
        if "%" in code:
            helpers.append({'kind': 'operator', 'name': '%', 'description': '나머지 연산자'})
        if "round(" in code or ":.2f" in code or ":.1f" in code:
            helpers.append({'kind': 'function', 'name': 'round() / :.2f', 'description': '소수점 자릿수 제한 포맷팅 도구'})
        if "float(" in code or "int(" in code:
            helpers.append({'kind': 'function', 'name': 'float() / int()', 'description': '문자열 또는 숫자의 자료형 변환 도구'})
        if "len(" in code:
            helpers.append({'kind': 'function', 'name': 'len()', 'description': '문자열 또는 시퀀스의 길이(글자 수) 반환'})
        if "input(" in code:
            helpers.append({'kind': 'function', 'name': 'input()', 'description': '사용자 입력 수신 함수 (문자열 반환)'})

        # 3. 기존 클래스 메서드 및 인스턴스 속성 추출 로직
        try:
            tree = ast.parse(code)
            funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        except Exception:
            funcs = []

        for f in funcs:
            if f.name not in ('__init__', target_func_name):
                ds = ast.get_docstring(f)
                desc = ds.strip() if ds else cls.COMMON_DSA_FUNC_DESCS.get(f.name, f"{f.name}() 보조 연산 수행")
                helpers.append({
                    'kind': 'function',
                    'name': f"self.{f.name}()",
                    'description': desc
                })

        for f in funcs:
            if f.name == '__init__':
                attrs = set()
                for node in ast.walk(f):
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'self':
                        attrs.add(node.attr)
                for attr in sorted(list(attrs)):
                    desc = cls.COMMON_DSA_ATTR_DESCS.get(attr, f"클래스 인스턴스 변수 ({attr})")
                    helpers.append({
                        'kind': 'variable',
                        'name': f"self.{attr}",
                        'description': desc
                    })

        if helpers:
            guide_lines.append("• 권장 사용 도구 및 연산자:")
            for h in helpers:
                guide_lines.append(f"  - `{h['name']}`: {h['description']}")

        if not guide_lines:
            return {'available_helpers': [], 'helpers_guide_text': ''}

        full_guide = "💡 [사용 권장 도구 및 공식 가이드라인]\n" + '\n'.join(guide_lines)
        return {
            'available_helpers': helpers,
            'helpers_guide_text': full_guide
        }

    @classmethod
    def generate_full_coding_problem(cls, code: str, target_func_name: str = None,
                                     client=None, slide_text: str = None, concept_id: str = None,
                                     title: str = None, description: str = None, requirements: list = None) -> dict:
        """클래스나 여러 함수가 포함된 코드에서 헤더/보조 함수들을 온전히 보존하고,
        학생이 작성할 핵심 대상 함수만 비워둔 풀코딩(Full-Coding) 문제 및 스타터 코드를 자동 생성합니다.

        * 헤더 함수(Header / Context Functions):
          - class 선언부, __init__, 헬퍼 함수(is_empty, is_full 등)를 원형 그대로 보존
          - 프론트엔드 에디터 상단에 기본 베이스 코드(또는 Read-Only 블록)로 띄워줌
        * 대상 함수(Target Function):
          - 함수 시그니처(헤더 선언부, 예: def pop(self):)만 남겨두고 본문은 pass 플레이스홀더로 교체
          - 학생이 직접 키보드로 전체 로직을 채워 넣을 수 있는 starter_code 제공
        """
        lines = code.splitlines()
        try:
            tree = ast.parse(code)
            funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        except Exception:
            funcs = []

        if not funcs:
            problem_meta = cls.generate_practice_statement(
                code=code, client=client, slide_text=slide_text,
                concept_id=concept_id, title=title, description=description, requirements=requirements
            )
            helper_meta = cls.extract_available_helpers(code, slide_text=slide_text)
            return {
                'target_function_name': None,
                'target_signature': None,
                'target_code': code,
                'starter_code': '# 여기에 알고리즘 전체 코드를 작성하세요.\n',
                'header_code': '',
                'available_helpers': helper_meta['available_helpers'],
                'helpers_guide_text': helper_meta['helpers_guide_text'],
                'flow_steps': problem_meta.get('flow_steps', []),
                'title': problem_meta['title'],
                'description': problem_meta['description'],
                'requirements': problem_meta['requirements'],
                'statement_source': problem_meta.get('source', 'rule_fallback')
            }

        # 대상 함수(Target Function) 결정
        target_f = None
        if target_func_name:
            for f in funcs:
                if f.name == target_func_name:
                    target_f = f
                    break
        if not target_f:
            non_init = [f for f in funcs if f.name != '__init__']
            if non_init:
                best_score = -1
                for f in non_init:
                    end_ln = getattr(f, 'end_lineno', f.lineno)
                    score = max((cls.score_line(lines[i])[0] for i in range(f.lineno - 1, min(end_ln, len(lines)))), default=0)
                    if score > best_score:
                        best_score = score
                        target_f = f
            if not target_f:
                target_f = funcs[0]

        start_idx = target_f.lineno - 1
        end_idx = getattr(target_f, 'end_lineno', len(lines))
        target_lines = lines[start_idx:end_idx]
        target_code = '\n'.join(target_lines)

        sig_line = target_lines[0]
        indent = sig_line[:len(sig_line) - len(sig_line.lstrip())]
        body_indent = indent + '    '

        ds = ast.get_docstring(target_f)
        doc_part = f'\n{body_indent}"""{ds}"""' if ds else ''
        todo_stub = f"{sig_line}{doc_part}\n{body_indent}# [TODO] 여기에 {target_f.name} 연산 로직을 구현하세요\n{body_indent}pass"

        # starter_code: 진정한 풀코딩 원칙에 따라 에디터는 완전한 백지(Blank Canvas, 빈 문자열)로 제공!
        # 헤더 함수(class, __init__, is_empty 등)는 에디터에 미리 채우지 않고 오직 좌측 지문 안내창에만 제공합니다.
        starter_code = "\n".join(lines[:start_idx] + [todo_stub] + lines[end_idx:])

        # header_code: 대상 함수를 제외한 클래스 선언 및 헬퍼 함수들 (채점 및 백엔드 실행 컨텍스트용)
        header_lines = lines[:start_idx] + lines[end_idx:]
        header_code = '\n'.join(header_lines).strip()

        problem_meta = cls.generate_practice_statement(
            code=target_code,
            client=client,
            slide_text=slide_text,
            concept_id=concept_id or target_f.name,
            title=title,
            description=description,
            requirements=requirements
        )

        helper_meta = cls.extract_available_helpers(code, target_f.name, slide_text=slide_text)

        return {
            'target_function_name': target_f.name,
            'target_signature': sig_line.strip(),
            'target_code': target_code,
            'starter_code': starter_code,
            'header_code': header_code,
            'available_helpers': helper_meta['available_helpers'],
            'helpers_guide_text': helper_meta['helpers_guide_text'],
            'flow_steps': problem_meta.get('flow_steps', []),
            'title': problem_meta['title'],
            'description': problem_meta['description'],
            'requirements': problem_meta['requirements'],
            'statement_source': problem_meta.get('source', 'rule_fallback')
        }

    # =========================================================================
    # 실습실 3대 엔진: AST 오타 감지, 안전 샌드박스 실행(stdout), 3-스트라이크 Ghost Text
    # =========================================================================

    @classmethod
    def execute_practice_code(cls, code: str, header_code: str = "", target_func_name: str = "") -> dict:
        """Student code must go through lerny.tracing's disposable worker."""
        raise RuntimeError("ISOLATED_WORKER_REQUIRED")

    @staticmethod
    def check_ast_syntax(code: str) -> dict:
        """0.001초 만에 학생 코드의 구문 오류(SyntaxError)를 감지하고 친절한 한국어 안내를 반환합니다.
        
        단순 오타로 인해 3-스트라이크 기회가 깎이지 않도록 사전 검증 역할을 합니다.
        """
        if not code or not code.strip():
            return {
                "is_valid": True,
                "error_type": None,
                "error_line": None,
                "error_message": None
            }
        try:
            ast.parse(code)
            return {
                "is_valid": True,
                "error_type": None,
                "error_line": None,
                "error_message": None
            }
        except SyntaxError as e:
            line_no = e.lineno or 1
            lines = code.splitlines()
            err_line = lines[line_no - 1] if 0 <= line_no - 1 < len(lines) else ""
            msg = e.msg or ""

            friendly = f"{line_no}번째 줄: 문법 오류가 감지되었습니다."
            if "expected ':'" in msg or (":" not in err_line and any(err_line.strip().startswith(kw) for kw in ("if", "elif", "else", "for", "while", "def", "class", "try", "except", "finally", "with"))):
                friendly = f"{line_no}번째 줄 끝에 콜론(:)이 누락되었습니다."
            elif "unexpected indent" in msg or "unindent does not match" in msg:
                friendly = f"{line_no}번째 줄: 들여쓰기(Indent)가 맞지 않습니다. (스페이스 4칸을 확인하세요)"
            elif "was never closed" in msg or "closing parenthesis" in msg or "unmatched" in msg:
                friendly = f"{line_no}번째 줄: 괄호() 또는 대괄호[]의 짝이 닫히지 않았습니다."
            elif "EOL while scanning" in msg or "unterminated string" in msg:
                friendly = f"{line_no}번째 줄: 문자열 따옴표(\" 또는 ')가 닫히지 않았습니다."
            elif "invalid syntax" in msg and err_line.strip().endswith("="):
                friendly = f"{line_no}번째 줄: 할당 연산자(=) 뒤에 값이 누락되었습니다."

            return {
                "is_valid": False,
                "error_type": "SyntaxError",
                "error_line": line_no,
                "error_column": e.offset,
                "raw_message": msg,
                "error_message": friendly
            }

    @staticmethod
    def evaluate_blank_answer(user_answer: str, target_answer: str) -> dict:
        """Syntax equivalence only; production uses isolated multiple-input cases."""
        import ast
        import textwrap
        def normalized(value):
            return ast.dump(ast.parse(textwrap.dedent(value).strip()), include_attributes=False)
        try:
            correct = normalized(user_answer) == normalized(target_answer)
        except (SyntaxError, ValueError):
            correct = user_answer.strip() == target_answer.strip()
        return {"correct": correct, "is_correct": correct,
                "message": "일치합니다." if correct else "조건과 연산을 다시 확인해 보세요."}

    @staticmethod
    def check_strike_and_build_ghost_text(problem_id: str, attempt_count: int, hints_used: int, answer_code: str, student_weakness_weight: float = 0.0) -> dict:
        """3-스트라이크 룰을 검사하고 충족 시 복사 방지용 Ghost Text 페이로드를 생성합니다.
        
        * 실습실 심리적 안전지대 원칙: student_weakness_weight는 0.0(0%)으로 강제되어
          학생 취약도 점수(W_final)에 절대 반영되지 않습니다.
        """
        is_strike_out = (attempt_count >= 3) or (hints_used >= 3)
        remaining = max(0, 3 - attempt_count)

        if not is_strike_out:
            return {
                "problem_id": problem_id,
                "can_reveal_answer": False,
                "attempt_count": attempt_count,
                "hints_used": hints_used,
                "remaining_attempts": remaining,
                "student_weakness_weight": 0.0,
                "ghost_text_payload": None
            }

        return {
            "problem_id": problem_id,
            "can_reveal_answer": True,
            "attempt_count": attempt_count,
            "hints_used": hints_used,
            "remaining_attempts": 0,
            "student_weakness_weight": 0.0,
            "ghost_text_payload": {
                "target_code": (answer_code or "").strip(),
                "allow_copy_paste": False,
                "display_mode": "inline_ghost",
                "guide_message": "정답 코드가 에디터에 회색 글씨로 표시됩니다. 직접 키보드로 따라 치면서 로직을 손으로 체득해 보세요!"
            }
        }

    # =========================================================================
    # 🧠 연상 기억 흐름 (Mnemonic Action Flow) 힌트 카탈로그
    # (단순 힌트 횟수가 아닌, 코드를 직관적으로 떠올릴 수 있는 스토리 기반 단계 가이드)
    # =========================================================================

    MNEMONIC_FLOW_CATALOG = {
        'stack_pop': {
            'flow_title': '🎬 pop() 연산을 쉽게 기억하는 4단계 행동 흐름',
            'metaphor': '프링글스 통/접시 더미에서 맨 위 과자를 하나 꺼내 맛보는 과정',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [확인하기 - 빈 통인가?]',
                    'action_story': '과자를 집으려고 손을 넣기 전, 통이 비어있으면 집을 수 없겠죠? 먼저 빈 통인지 if 조건문으로 확인하고 빠져나옵니다.',
                    'code_mnemonic': 'if [비어 있는 조건]: [예외 처리]'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [손에 쥐기 - 떨어뜨리지 않게 보관]',
                    'action_story': '맨 위 과자를 잡았습니다. 통의 번호표를 바꾸기 전, 손(임시 변수)에 먼저 안전하게 쥐고 있어야 과자가 사라지지 않아요!',
                    'code_mnemonic': '[임시 변수] = [꺼낼 원소]'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [높이 낮추기 - 맨 위 위치 갱신]',
                    'action_story': '과자를 하나 꺼냈으니, 통 안에 남아있는 가장 위 과자의 번호표(top)를 한 칸 아래로 내려줍니다.',
                    'code_mnemonic': '[위치] = [꺼낸 뒤의 위치]'
                },
                {
                    'step_number': 4,
                    'title': '4️⃣ [건네주기 - 꺼낸 과자 맛있게 반환]',
                    'action_story': '이제 2단계에서 손에 쥐어두었던 과자를 호출자에게 return으로 건네주며 연산을 마칩니다.',
                    'code_mnemonic': 'return [꺼낸 원소]'
                }
            ]
        },
        'stack_push': {
            'flow_title': '🎬 push() 연산을 쉽게 기억하는 3단계 행동 흐름',
            'metaphor': '프링글스 통 위에 새 과자를 안전하게 쌓아 올리는 과정',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [공간 확인 - 꽉 찬 통인가?]',
                    'action_story': '새 과자를 넣기 전, 통이 이미 가득 찼는지 포화(Overflow) 상태를 먼저 확인합니다.',
                    'code_mnemonic': 'if [포화 조건]: [예외 처리]'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [자리 만들기 - 맨 위 번호표 올리기]',
                    'action_story': '새 과자가 들어갈 윗자리 번호표를 하나 늘립니다.',
                    'code_mnemonic': '[위치] = [삽입할 위치]'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [과자 안착 - 새 자리에 쏙 넣기]',
                    'action_story': '새로 준비된 top 위치에 새 과자를 안전하게 내려놓습니다.',
                    'code_mnemonic': '[저장 위치] = [새 원소]'
                }
            ]
        },
        'queue_enqueue': {
            'flow_title': '🎬 enqueue() 연산을 쉽게 기억하는 3단계 행동 흐름',
            'metaphor': '원형 회전초밥 레일에 새 접시를 올리는 과정',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [만석 검사 - 다음 자리가 찼는가?]',
                    'action_story': '내 다음에 넣을 자리에 이미 다른 손님(front)이 앉아있다면 만석(Full)입니다!',
                    'code_mnemonic': 'if [큐가 가득 찬 조건]: [예외 처리]'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [레일 회전 - 시계처럼 한 칸 돌리기]',
                    'action_story': '배열 끝에 닿으면 다시 맨 앞(0번)으로 돌아와야 하므로 % 연산으로 시계처럼 한 칸 돌립니다.',
                    'code_mnemonic': '[뒤쪽 위치] = [다음 위치]'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [접시 놓기 - 새로 이동한 자리에 저장]',
                    'action_story': '새로 이동한 rear 자리에 손님이 가져온 데이터를 내려놓습니다.',
                    'code_mnemonic': '[저장 위치] = [새 원소]'
                }
            ]
        },
        'binary_search': {
            'flow_title': '🎬 binary_search()를 쉽게 기억하는 5단계 행동 흐름',
            'metaphor': '업앤다운(Up & Down) 숫자 맞추기 게임',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [양 끝 깃발 세우기]',
                    'action_story': '탐색할 범위의 맨 왼쪽 끝(0)과 오른쪽 끝(len-1)에 경계선 깃발을 세웁니다.',
                    'code_mnemonic': '[왼쪽 경계], [오른쪽 경계] = [범위의 양 끝]'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [깃발 엇갈림 검사 루프]',
                    'action_story': '두 깃발이 서로 지나치지 않는 동안 계속 탐색을 반복합니다.',
                    'code_mnemonic': 'while [탐색 범위가 남은 조건]:'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [정중앙 찌르기]',
                    'action_story': '가장 확률이 높은 딱 정가운데 위치(mid)를 계산하여 비교합니다.',
                    'code_mnemonic': '[중간 위치] = [경계로 계산한 위치]'
                },
                {
                    'step_number': 4,
                    'title': '4️⃣ [절반 버리기 (업? 다운?)]',
                    'action_story': '목표값이 더 크면 왼쪽 절반은 쳐다볼 필요도 없으니 왼쪽 깃발을 옮깁니다.',
                    'code_mnemonic': '[남길 구간의 경계] = [다음 경계]'
                },
                {
                    'step_number': 5,
                    'title': '5️⃣ [포기하고 돌아가기]',
                    'action_story': '두 깃발이 엇갈릴 때까지 못 찾았으면 목록에 없다는 뜻이므로 -1을 반환합니다.',
                    'code_mnemonic': 'return [찾지 못한 결과]'
                }
            ]
        },
        'bmi': {
            'flow_title': '🎬 BMI 계산을 완성하는 3단계 행동 흐름',
            'metaphor': '단위를 맞추고 공식에 대입하여 체질량지수 계산하기',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [단위 변환 - 계산 단위 정합화]',
                    'action_story': '입력받은 키(height)는 cm 단위입니다. BMI 공식에 대입하기 위해 먼저 미터(m) 단위로 환산하는 전처리 연산을 수행하세요.',
                    'code_mnemonic': '[키] = [키] / [환산단위]'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [체질량지수(BMI) 계산]',
                    'action_story': '체질량지수는 키와 몸무게로 구하는 지표입니다. 단위를 확인한 후 계산 결과를 저장하세요.',
                    'code_mnemonic': '[체질량지수] = [단위를 맞춘 계산식]'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [소수점 서식 맞춤 출력]',
                    'action_story': "f-string 또는 서식 지정자(:.2f)를 활용하여 예시 출력과 동일한 형식(소수점 둘째 자리)으로 결과를 화면에 출력하세요.",
                    'code_mnemonic': "print(f'BMI : {[bmi]:.2f}')"
                }
            ]
        },
        'arithmetic': {
            'flow_title': '🎬 사칙연산 프로그램을 완성하는 3단계 행동 흐름',
            'metaphor': '계산기 버튼을 순서대로 누르듯 각각의 연산 결과 도출하기',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [두 수 준비]',
                    'action_story': '계산 대상이 되는 두 변수의 값을 확인하고 준비합니다.',
                    'code_mnemonic': '[변수 준비]'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [사칙연산 수행]',
                    'action_story': '덧셈(+), 뺄셈(-), 곱셈(*), 나눗셈(/) 연산자를 적용하여 각 연산을 계산합니다. (나눗셈은 실수 float로 계산됩니다)',
                    'code_mnemonic': '[변수] [연산자] [변수]'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [형식에 맞춘 출력]',
                    'action_story': "예시 출력 형식에 맞추어 콜론(:)과 공백을 지키며 print() 함수로 결과를 출력하세요.",
                    'code_mnemonic': "print('[라벨] :', [연산결과])"
                }
            ]
        },
        'string_len': {
            'flow_title': '🎬 문자열 분석 프로그램을 완성하는 3단계 행동 흐름',
            'metaphor': '기차 칸을 하나씩 세어 전체 길이를 파악하기',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [문자열 변수 확인]',
                    'action_story': '분석 대상이 되는 문자열 변수를 확인합니다.',
                    'code_mnemonic': '[문자열 변수 확인]'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [len() 함수 적용]',
                    'action_story': '공백과 특수문자를 포함한 모든 글자의 개수를 len() 함수로 구합니다.',
                    'code_mnemonic': '[길이변수] = len([문자열])'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [결과 출력]',
                    'action_story': '계산된 글자 수를 요구된 형식에 맞춰 출력합니다.',
                    'code_mnemonic': 'print([길이변수])'
                }
            ]
        },
        'grade_average': {
            'flow_title': '🎬 성적 처리 프로그램을 완성하는 4단계 행동 흐름',
            'metaphor': '과목별 점수를 모아 총점을 내고, 평균을 산출하여 출력하기',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [입력 준비 및 점수 변수 확인]',
                    'action_story': '각 과목의 점수 변수가 선언되어 있는지 확인합니다.',
                    'code_mnemonic': '[과목 점수 확인]'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [총점 합산 - 누적 덧셈]',
                    'action_story': '모든 과목의 점수를 덧셈(+) 연산자로 더하여 total 변수에 합산 저장하세요.',
                    'code_mnemonic': '[총점변수] = [점수 집계식]'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [평균 계산 - 나눗셈 연산]',
                    'action_story': '앞서 구한 총점(total)을 과목 수로 나눗셈(/)하여 평균 avg 변수를 계산하세요.',
                    'code_mnemonic': '[평균변수] = [평균 계산식]'
                },
                {
                    'step_number': 4,
                    'title': '4️⃣ [형식에 맞춘 결과 출력]',
                    'action_story': '요구된 예시 출력 형식에 맞추어 print() 함수 또는 f-string으로 총점과 평균을 정확히 출력하세요.',
                    'code_mnemonic': 'print(f"[라벨] : {[변수]}")'
                }
            ]
        }
    }

    GENERIC_ACTION_FLOW = {
        'flow_title': '🎬 알고리즘 구현을 위한 직관적 행동 흐름 (Action Flow)',
        'metaphor': '컴퓨터공학 표준 1인칭 행동 모델 (확인 ➔ 보관 ➔ 갱신 ➔ 반환)',
        'steps': [
            {
                'step_number': 1,
                'title': '1️⃣ [안전 확인 - 경계/예외 조건]',
                'action_story': '연산을 시작하기 전, 예외가 발생할 수 있는 경계 조건(빈 상태, 인덱스 초과 등)을 if문으로 먼저 확인하여 방어합니다.',
                'code_mnemonic': 'if [경계 조건]:'
            },
            {
                'step_number': 2,
                'title': '2️⃣ [핵심 처리 - 대상 데이터 포착]',
                'action_story': '연산의 대상이 되는 핵심 원소를 임시 변수에 안전하게 담거나 계산/탐색을 수행합니다.',
                'code_mnemonic': 'item = ...'
            },
            {
                'step_number': 3,
                'title': '3️⃣ [상태 전이 - 포인터 및 인덱스 갱신]',
                'action_story': '연산 결과에 맞춰 자료구조의 상태(포인터 번호표 증감, 인덱스 이동, 링크 재연결)를 갱신합니다.',
                'code_mnemonic': '[위치] = [꺼낸 뒤의 위치]'
            },
            {
                'step_number': 4,
                'title': '4️⃣ [결과 건네주기 - 최종 반환]',
                'action_story': '준비된 결과값을 호출한 곳으로 return하며 함수를 완성합니다.',
                'code_mnemonic': 'return [꺼낸 원소]'
            }
        ]
    }

    @classmethod
    def generate_dynamic_action_flow(cls, code: str, title: str = None) -> dict:
        """임의의 파이썬 코드를 AST로 분석하여 해당 문제 맞춤형 3~4단계 Action Flow를 동적 생성합니다."""
        steps = []
        code_str = (code or "").strip()
        lines = [l.strip() for l in code_str.splitlines() if l.strip() and not l.strip().startswith("#")]

        # 변수 및 구문 요소 추출
        init_vars = []
        calc_stmts = []
        cond_stmts = []
        body = []
        loop_stmts = []
        output_stmts = []
        return_stmts = []
        all_vars = []
        all_ops = []

        try:
            tree = ast.parse(code_str)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id not in ("print", "len", "int", "float", "str", "True", "False", "None"):
                    all_vars.append(node.id)
                elif isinstance(node, ast.Add):
                    all_ops.append("덧셈(+)")
                elif isinstance(node, (ast.Div, ast.FloorDiv)):
                    all_ops.append("나눗셈(/)")
                elif isinstance(node, ast.Mult):
                    all_ops.append("곱셈(*)")
                elif isinstance(node, ast.Pow):
                    all_ops.append("거듭제곱(**)")
                elif isinstance(node, ast.Sub):
                    all_ops.append("뺄셈(-)")
                elif isinstance(node, ast.Mod):
                    all_ops.append("나머지(%)")

            # 순차적 문장 순회
            body = tree.body
            if body and isinstance(body[0], ast.FunctionDef):
                body = body[0].body

            for stmt in body:
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    target_names = []
                    if isinstance(stmt, ast.Assign):
                        for t in stmt.targets:
                            if isinstance(t, ast.Name):
                                target_names.append(t.id)
                            elif isinstance(t, ast.Attribute):
                                target_names.append(f"{ast.unparse(t.value)}.{t.attr}" if hasattr(ast, "unparse") else t.attr)
                    elif hasattr(stmt, "target") and isinstance(stmt.target, ast.Name):
                        target_names.append(stmt.target.id)

                    val = getattr(stmt, "value", None)
                    if isinstance(val, (ast.Constant, ast.Num, ast.Str)):
                        init_vars.extend(target_names)
                    elif isinstance(val, ast.Call) and getattr(val.func, "id", "") == "input":
                        init_vars.extend(target_names)
                    else:
                        calc_stmts.append((target_names, val, stmt))
                elif isinstance(stmt, ast.AugAssign):
                    t_name = getattr(stmt.target, "id", "")
                    calc_stmts.append(([t_name], stmt.value, stmt))
                elif isinstance(stmt, (ast.For, ast.While)):
                    loop_stmts.append(stmt)
                elif isinstance(stmt, ast.Return):
                    return_stmts.append(stmt)
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    fname = getattr(stmt.value.func, "id", getattr(stmt.value.func, "attr", ""))
                    if fname == "print":
                        output_stmts.append(stmt)
                    else:
                        calc_stmts.append(([], stmt.value, stmt))
            cond_stmts = sorted((n for stmt in body for n in ast.walk(stmt) if isinstance(n, ast.If)),
                                key=lambda n: n.lineno)
        except Exception:
            pass

        init_vars = list(dict.fromkeys(init_vars))
        all_vars = list(dict.fromkeys(all_vars))
        all_ops = list(dict.fromkeys(all_ops))

        # 1단계: 입력 및 상태 준비
        opening_guard = bool(cond_stmts and body and cond_stmts[0] is body[0]
                             and not init_vars and (loop_stmts or calc_stmts))
        if opening_guard:
            cond_node = cond_stmts[0]
            cond_str = ast.unparse(cond_node.test) if hasattr(ast, "unparse") else "조건식"
            cond_skel = cls.build_abstract_skeleton(f"if {cond_str}:") or "if [경계조건]:"
            steps.append({
                'step_number': 1,
                'title': '1️⃣ [안전 확인 - 경계/예외 조건 점검]',
                'action_story': '연산을 시작하기 전, 예외가 발생하거나 빈 상태가 되는 경계 조건을 if 조건문으로 먼저 점검하고 방어합니다.',
                'code_mnemonic': cond_skel
            })
        elif init_vars:
            steps.append({
                'step_number': 1,
                'title': '1️⃣ [입력 준비 및 변수 확인]',
                'action_story': f'시작에 필요한 입력 변수({", ".join(init_vars[:4])})가 선언되어 있는지 확인하고 준비합니다.',
                'code_mnemonic': f'{", ".join(init_vars[:3])} 값 확인'
            })
        else:
            steps.append({
                'step_number': 1,
                'title': '1️⃣ [입력 데이터 및 시작 조건 준비]',
                'action_story': '문제에서 주어진 입력값과 사용할 변수의 역할을 확인하고 준비합니다.',
                'code_mnemonic': '입력값 및 변수 초기화'
            })

        # 2단계: 핵심 연산 / 반복 / 조건 처리
        if loop_stmts:
            loop_node = loop_stmts[0]
            loop_str = ast.unparse(loop_node) if hasattr(ast, "unparse") else "반복문"
            loop_hdr = loop_str.splitlines()[0] if loop_str else "for / while"
            loop_skel = cls.build_abstract_skeleton(loop_hdr) or "for / while [반복조건]:"
            steps.append({
                'step_number': 2,
                'title': '2️⃣ [반복 탐색 및 누적 연산]',
                'action_story': '반복문(for / while)을 통해 데이터 시퀀스나 범위를 순회하며 목표 연산을 수행합니다.',
                'code_mnemonic': loop_skel
            })
        elif calc_stmts:
            first_targets, first_val, first_stmt = calc_stmts[0]
            t_str = ", ".join(first_targets) if first_targets else "목표 변수"
            unparsed = ast.unparse(first_stmt) if hasattr(ast, "unparse") else f"{t_str} 계산"
            op_str = f" ({', '.join(all_ops)})" if all_ops else ""
            steps.append({
                'step_number': 2,
                'title': '2️⃣ [핵심 계산 - 공식 및 연산자 적용]',
                'action_story': f'주어진 조건과 연산자{op_str}를 활용하여 `{t_str}`의 값을 계산합니다.',
                'code_mnemonic': cls.build_abstract_skeleton(unparsed) or f"[{t_str}] = [연산식]"
            })
        elif cond_stmts:
            cond_node = cond_stmts[0]
            cond_str = ast.unparse(cond_node.test) if hasattr(ast, "unparse") else "조건 비교"
            cond_skel = cls.build_abstract_skeleton(f"if {cond_str}:") or "if [조건식]:"
            steps.append({
                'step_number': 2,
                'title': '2️⃣ [조건 판별 및 분기 실행]',
                'action_story': '문제에서 요구한 대소 비교 및 복합 논리 판별식(if)을 작성하여 참/거짓 분기 처리를 수행합니다.',
                'code_mnemonic': cond_skel
            })
        else:
            steps.append({
                'step_number': 2,
                'title': '2️⃣ [핵심 알고리즘 로직 처리]',
                'action_story': '요구조건에 맞추어 변수들 사이의 연산과 처리를 수행합니다.',
                'code_mnemonic': '[변수] = [연산식]'
            })

        # 3단계: 상태 갱신 / 후속 계산
        if cond_stmts and (loop_stmts or calc_stmts) and not opening_guard:
            condition = ast.unparse(cond_stmts[0].test)
            steps.append({"step_number": len(steps) + 1, "title": "조건 판별 및 분기",
                          "action_story": "각 조건을 확인하고 해당하는 분기에서 수행할 처리를 선택하세요.",
                          "code_mnemonic": cls.build_abstract_skeleton(f"if {condition}:")})
        elif len(calc_stmts) > 1:
            sec_targets, sec_val, sec_stmt = calc_stmts[1]
            sec_t_str = ", ".join(sec_targets) if sec_targets else "후속 변수"
            sec_unparsed = ast.unparse(sec_stmt) if hasattr(ast, "unparse") else f"{sec_t_str} 계산"
            steps.append({
                'step_number': 3,
                'title': '3️⃣ [결과 계산 및 상태 갱신]',
                'action_story': f'앞서 구한 연산 결과를 활용하여 `{sec_t_str}` 값을 추가로 계산하거나 포인터/상태를 갱신합니다.',
                'code_mnemonic': cls.build_abstract_skeleton(sec_unparsed) or f"[{sec_t_str}] = [연산식]"
            })
        elif any("self." in l for l in lines):
            steps.append({
                'step_number': 3,
                'title': '3️⃣ [자료구조 상태 및 포인터 갱신]',
                'action_story': '연산 결과에 맞추어 인덱스 위치나 포인터 변수의 값을 한 칸 이동하여 상태를 갱신합니다.',
                'code_mnemonic': '포인터 위치 갱신'
            })

        # 4단계 (또는 최종 단계): 출력 또는 반환
        if output_stmts:
            out_node = output_stmts[0]
            out_str = ast.unparse(out_node) if hasattr(ast, "unparse") else "print(...)"
            steps.append({
                'step_number': len(steps) + 1,
                'title': f'{len(steps) + 1}️⃣ [형식에 맞춘 결과 출력]',
                'action_story': f'예시 출력 서식(콜론, 공백, 소수점 등)에 맞추어 `print()` 함수로 계산된 결과를 콘솔에 출력합니다.',
                'code_mnemonic': cls.build_abstract_skeleton(out_str) or "print('[라벨] :', [출력변수])"
            })
        elif return_stmts:
            ret_node = return_stmts[0]
            ret_str = ast.unparse(ret_node) if hasattr(ast, "unparse") else "return 결과"
            steps.append({
                'step_number': len(steps) + 1,
                'title': f'{len(steps) + 1}️⃣ [최종 결과 반환]',
                'action_story': f'준비된 결과값을 호출한 곳으로 `return`하며 함수의 실행을 정상적으로 마칩니다.',
                'code_mnemonic': 'return [결과값]'
            })
        else:
            steps.append({
                'step_number': len(steps) + 1,
                'title': f'{len(steps) + 1}️⃣ [최종 결과 전달 및 마무리]',
                'action_story': '계산된 최종 결과가 문제의 요구사항과 일치하는지 점검하고 출력을 완성합니다.',
                'code_mnemonic': '결과 출력 또는 반환'
            })

        # 3~4단계 규격 보정
        for i, s in enumerate(steps, 1):
            s['step_number'] = i
            # 제목 번호 일치
            clean_t = re.sub(r'^[1-9]️⃣\s*', '', s['title'])
            num_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
            emoji = num_emojis[i - 1] if i <= len(num_emojis) else f'{i}단계'
            s['title'] = f"{emoji} {clean_t}"

        prob_name = title or "알고리즘"
        return {
            'flow_title': f'🎬 {prob_name} 구현을 완성하는 {len(steps)}단계 행동 흐름',
            'metaphor': f'{prob_name}의 논리적 실행 단계',
            'steps': steps
        }

    @staticmethod
    def data_hint_topic(code, title=""):
        """Return a specialised hint only when the code supports the interpretation."""
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            return None
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assignments = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
        if ("mid" in names and ({"low", "high"} <= names or {"left", "right"} <= names)
                and any(isinstance(n, ast.While) for n in ast.walk(tree))):
            return "binary_search"
        def string_value(value):
            return (isinstance(value, ast.Constant) and isinstance(value.value, str)
                    or isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"str", "input"})
        bindings = {}
        for assignment in assignments:
            for target in assignment.targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, set()).add(string_value(assignment.value))
        strings = {name for name, types in bindings.items() if types == {True}}
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            if isinstance(call.func, ast.Name) and call.func.id == "len" and len(call.args) == 1:
                arg = call.args[0]
                if string_value(arg) or isinstance(arg, ast.Name) and arg.id in strings:
                    return "string_len"
        grades = bool({"kor", "eng"} <= names or any("score" in n or "grade" in n for n in names)
                      or any(word in title.lower() for word in ("성적", "점수", "grade", "score")))
        if grades and any(isinstance(a.value, ast.BinOp) and isinstance(a.value.op, ast.Div)
               and any(isinstance(t, ast.Name) and t.id.lower() in {"avg", "average", "mean"} for t in a.targets)
               for a in assignments):
            return "grade_average"
        return None

    @classmethod
    def resolve_mnemonic_flow(cls, exercise_id: str = '', target_code: str = '', metaphor: str = None, flow_steps: list = None) -> dict:
        """문제 ID 또는 코드 형태를 분석하여 적절한 멘탈 모델 연상 기억 흐름을 반환합니다."""
        if flow_steps and isinstance(flow_steps, list) and len(flow_steps) > 0:
            formatted_steps = []
            for idx, s in enumerate(flow_steps, 1):
                if isinstance(s, dict):
                    formatted_steps.append({
                        'step_number': idx,
                        'title': s.get('title', f'{idx}단계'),
                        'action_story': s.get('action_story', s.get('story', str(s))),
                        'code_mnemonic': s.get('code_mnemonic', s.get('code', ''))
                    })
                else:
                    formatted_steps.append({
                        'step_number': idx,
                        'title': f'{idx}단계',
                        'action_story': str(s),
                        'code_mnemonic': ''
                    })
            return {
                'flow_title': '🎬 커스텀 로직 흐름 가이드',
                'metaphor': metaphor or '커스텀 알고리즘 구현 흐름',
                'steps': formatted_steps
            }

        eid = (exercise_id or '').lower()
        tcode = (target_code or '').lower()

        matched_key = None
        if 'pop' in eid or 'def pop' in tcode:
            matched_key = 'stack_pop'
        elif 'push' in eid or 'def push' in tcode:
            matched_key = 'stack_push'
        elif 'enqueue' in eid or 'enqueue' in tcode:
            matched_key = 'queue_enqueue'
        elif 'binary_search' in eid or re.search(r'\bdef\s+binary_search\b', tcode):
            matched_key = 'binary_search'
        elif 'bmi' in eid or 'bmi' in tcode or ('height' in tcode and 'weight' in tcode):
            matched_key = 'bmi'
        elif '사칙연산' in eid or 'arithmetic' in eid or ('덧셈' in tcode and '나눗셈' in tcode):
            matched_key = 'arithmetic'
        else:
            matched_key = cls.data_hint_topic(target_code or "", eid)


        if matched_key and matched_key in cls.MNEMONIC_FLOW_CATALOG:
            base = cls.MNEMONIC_FLOW_CATALOG[matched_key]
        elif target_code and target_code.strip():
            # 카탈로그에 없는 임의의 문제도 코드의 AST를 분석하여 살아있는 동적 Action Flow 자동 생성!
            base = cls.generate_dynamic_action_flow(target_code, title=exercise_id)
        else:
            base = cls.GENERIC_ACTION_FLOW

        flow_copy = {
            'flow_title': base['flow_title'],
            'metaphor': metaphor or base['metaphor'],
            'steps': list(base['steps'])
        }
        if metaphor:
            flow_copy['flow_title'] = f"🎬 {metaphor} 비유 기반 {len(flow_copy['steps'])}단계 행동 흐름"

        return flow_copy

    @classmethod
    def get_practice_hint(cls, exercise_id: str, hint_step: int = 1, mode: str = 'full_coding', target_code: str = '', attempt_count: int = 0, metaphor: str = None, flow_steps: list = None, current_code: str = '', client=None) -> dict:
        """실습 퀴즈 [💡 힌트/로드맵] 요청 시 알고리즘 멘탈 모델 기반 연상 기억 흐름(Action Flow)을 제공합니다.
        
        * 핵심 특징:
          - 인위적 횟수 제한 없이, 알고리즘 구현의 자연스러운 단계별 행동 스토리(Step-by-Step) 제공
          - 교수님 비유(metaphor) 존재 시 비유 적극 계승, 부재 시 CS 표준 멘탈 모델 및 1인칭 행동 순서 안내
          - 학생 코드(current_code)에 문법 오류(SyntaxError)가 있을 시 syntax_warning으로 사전 피드백
          - 모든 단계를 끝까지 확인하거나 실행 3회 실패 시 [정답 보기] 활성화 (Ghost Text 워터마크 따라쓰기 강제)
          - 심리적 안전지대: student_weakness_weight = 0.0 (감점 0점)
        """
        flow = cls.practice_hint_flow(exercise_id, mode, target_code, metaphor, flow_steps)
        return cls._practice_hint_result(exercise_id, hint_step, mode, target_code, attempt_count,
                                         current_code, client, flow)

    @classmethod
    def _build_recursive_skeleton(cls, node) -> str:
        """AST 노드를 재귀적으로 탐색하여 실제 괄호와 연산자 구조를 완벽히 보존한 추상 골격을 생성합니다."""
        if isinstance(node, ast.BinOp):
            left_s = cls._build_recursive_skeleton(node.left)
            right_s = cls._build_recursive_skeleton(node.right)
            op_s = ("+" if isinstance(node.op, ast.Add) else
                    "-" if isinstance(node.op, ast.Sub) else
                    "*" if isinstance(node.op, ast.Mult) else
                    "/" if isinstance(node.op, ast.Div) else
                    "//" if isinstance(node.op, ast.FloorDiv) else
                    "%" if isinstance(node.op, ast.Mod) else
                    "**" if isinstance(node.op, ast.Pow) else "연산자")
            # 복합 수식의 우선순위 괄호 보존
            if isinstance(node.left, ast.BinOp):
                left_s = f"({left_s})"
            if isinstance(node.right, ast.BinOp):
                right_s = f"({right_s})"
            return f"{left_s} {op_s} {right_s}"
        elif isinstance(node, ast.Name):
            return f"[{node.id}]"
        elif isinstance(node, ast.Constant):
            if node.value is None:
                return "None"
            return '"[문자열]"' if isinstance(node.value, str) else "[상수값]"
        elif isinstance(node, ast.Call):
            fname = getattr(node.func, "id", getattr(node.func, "attr", "함수"))
            args_s = ", ".join(cls._build_recursive_skeleton(a) for a in node.args)
            return f"{fname}({args_s})"
        elif isinstance(node, ast.Compare):
            left_s = cls._build_recursive_skeleton(node.left)
            ops_map = {ast.Eq: "==", ast.NotEq: "!=", ast.Gt: ">", ast.Lt: "<", ast.GtE: ">=", ast.LtE: "<=",
                       ast.In: "in", ast.NotIn: "not in", ast.Is: "is", ast.IsNot: "is not"}
            parts = [left_s]
            for op, operand in zip(node.ops, node.comparators, strict=True):
                parts.extend((ops_map[type(op)], cls._build_recursive_skeleton(operand)))
            return " ".join(parts)
        elif isinstance(node, ast.BoolOp):
            op_s = " and " if isinstance(node.op, ast.And) else " or "
            values_s = [cls._build_recursive_skeleton(v) for v in node.values]
            joined = op_s.join(values_s)
            return f"({joined})"
        elif isinstance(node, ast.UnaryOp):
            op_s = "not " if isinstance(node.op, ast.Not) else "-" if isinstance(node.op, ast.USub) else ""
            val_s = cls._build_recursive_skeleton(node.operand)
            return f"{op_s}{val_s}"
        elif isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.FormattedValue):
                    val_s = cls._build_recursive_skeleton(v.value)
                    fmt_s = f":{v.format_spec.values[0].value}" if v.format_spec else ""
                    parts.append(f"{{{val_s}{fmt_s}}}")
                elif isinstance(v, ast.Constant):
                    parts.append(str(v.value))
            return f"f\"{''.join(parts)}\""
        elif isinstance(node, ast.Subscript):
            val_s = cls._build_recursive_skeleton(node.value)
            slice_s = cls._build_recursive_skeleton(node.slice)
            return f"{val_s}[{slice_s}]"
        return "[연산식]"

    @classmethod
    def build_abstract_skeleton(cls, line: str) -> str:
        """코드 한 줄에서 정답 코드(실제 수식, 상수값 등)를 직접 노출하지 않고
        문법적 구조와 괄호, 연산자, 변수 역할만 완벽히 드러내는 구조화된 추상 골격(Abstract Skeleton)으로 변환합니다."""
        clean = split_comment(line)[0].strip()
        if clean == "else:":
            return "else:"
        is_elif = re.match(r"elif\b", clean) is not None
        if is_elif:
            clean = "if" + clean[4:]
        if not clean:
            return ""
        try:
            line_to_parse = clean + "\n    pass" if clean.endswith(":") else clean
            tree = ast.parse(line_to_parse)
            if not tree.body:
                return "[코드 작성]"
            stmt = tree.body[0]
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                target_str = ""
                if isinstance(stmt, ast.Assign):
                    t = stmt.targets[0]
                    target_str = ast.unparse(t) if hasattr(ast, "unparse") else "결과변수"
                elif hasattr(stmt, "target"):
                    target_str = ast.unparse(stmt.target) if hasattr(ast, "unparse") else "결과변수"

                val_skel = cls._build_recursive_skeleton(stmt.value)
                return f"[{target_str}] = {val_skel}"
            elif isinstance(stmt, ast.AugAssign):
                target_str = ast.unparse(stmt.target) if hasattr(ast, "unparse") else "변수"
                op_sym = ("+=" if isinstance(stmt.op, ast.Add) else
                          "-=" if isinstance(stmt.op, ast.Sub) else
                          "*=" if isinstance(stmt.op, ast.Mult) else
                          "/=" if isinstance(stmt.op, ast.Div) else "대입연산")
                val_skel = cls._build_recursive_skeleton(stmt.value)
                return f"[{target_str}] {op_sym} {val_skel}"
            elif isinstance(stmt, ast.Expr):
                return cls._build_recursive_skeleton(stmt.value)
            elif isinstance(stmt, ast.If):
                test_skel = cls._build_recursive_skeleton(stmt.test)
                return ("elif " if is_elif else "if ") + test_skel + ":"
            elif isinstance(stmt, ast.For):
                t_str = ast.unparse(stmt.target) if hasattr(ast, "unparse") else "변수"
                iter_skel = cls._build_recursive_skeleton(stmt.iter)
                return f"for [{t_str}] in {iter_skel}:"
            elif isinstance(stmt, ast.While):
                test_skel = cls._build_recursive_skeleton(stmt.test)
                return f"while {test_skel}:"
            elif isinstance(stmt, ast.Return):
                if stmt.value:
                    return f"return {cls._build_recursive_skeleton(stmt.value)}"
                return "return"
        except Exception:
            pass
        return "[변수] = [연산식]"

    @classmethod
    def practice_hint_flow(cls, exercise_id, mode, target_code, metaphor=None, flow_steps=None):
        # 1. 빈칸 모드: 빈칸 대상 코드에 대한 0-스포일러 3단계 순차적 비계 힌트 (1: 목적 ➔ 2: 변수/문법 ➔ 3: 추상 골격)
        if mode == 'cloze':
            target_str = (target_code or '').strip()
            eid = (exercise_id or '').lower()
            lines = [l.strip() for l in target_str.splitlines() if l.strip() and not l.strip().startswith('#')]

            # AST 기반 범용 동적 요소 추출
            source_vars = []
            target_vars = []
            operators = []
            skeletons = []
            has_print = False
            has_pow = False
            has_div = False
            has_mod = False
            has_if = False
            has_func = []

            for line in lines:
                skel = cls.build_abstract_skeleton(line)
                if skel:
                    skeletons.append(skel)
                try:
                    line_clean = split_comment(line)[0].strip()
                    if line_clean == "else:":
                        has_if = True
                        continue
                    if re.match(r"elif\b", line_clean):
                        line_clean = "if" + line_clean[4:]
                    line_to_parse = line_clean + "\n    pass" if line_clean.endswith(":") else line_clean
                    tree = ast.parse(line_to_parse)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Name) and node.id not in ("print", "len", "int", "float", "str", "True", "False", "None"):
                            source_vars.append(node.id)
                        elif isinstance(node, ast.Add):
                            operators.append("덧셈(+)")
                        elif isinstance(node, (ast.Div, ast.FloorDiv)):
                            operators.append("나눗셈(/)")
                            has_div = True
                        elif isinstance(node, ast.Mult):
                            operators.append("곱셈(*)")
                        elif isinstance(node, ast.Pow):
                            operators.append("거듭제곱(**)")
                            has_pow = True
                        elif isinstance(node, ast.Sub):
                            operators.append("뺄셈(-)")
                        elif isinstance(node, ast.Mod):
                            operators.append("나머지(%)")
                            has_mod = True
                        elif isinstance(node, ast.Compare):
                            operators.append("비교 연산자(>=, <=, == 등)")
                        elif isinstance(node, ast.BoolOp):
                            operators.append("논리 연산자(and/or)")
                        elif isinstance(node, ast.Call):
                            fname = getattr(node.func, "id", getattr(node.func, "attr", ""))
                            if fname:
                                has_func.append(fname)
                            if fname == "print":
                                has_print = True
                        elif isinstance(node, ast.If):
                            has_if = True

                    for stmt in tree.body:
                        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                            if isinstance(stmt, ast.Assign):
                                for t in stmt.targets:
                                    if isinstance(t, ast.Name):
                                        target_vars.append(t.id)
                            elif hasattr(stmt, "target") and isinstance(stmt.target, ast.Name):
                                target_vars.append(stmt.target.id)
                except Exception:
                    pass

            source_vars = list(dict.fromkeys(source_vars))
            target_vars = list(dict.fromkeys(target_vars))
            operators = list(dict.fromkeys(operators))
            all_vars = list(dict.fromkeys(source_vars + target_vars))
            has_func = list(dict.fromkeys(has_func))

            # [1단계: 목적 파악 - 0-스포일러 연산 목표 동적 합성]
            # 정답 코드를 직접 노출하지 않고, 변수와 연산 특성으로부터 의도 중심 설명 생성
            topic = cls.data_hint_topic(target_str, eid)
            if 'bmi' in eid or '체질량' in eid or ('height' in all_vars and 'weight' in all_vars):
                step1_story = "이 빈칸은 입력된 키(cm)를 공식에 필요한 미터(m) 단위로 환산한 후, 체질량지수를 계산하여 결과를 산출하고 서식에 맞추어 출력하는 핵심 목표를 가집니다."
            elif topic == "grade_average":
                step1_story = "이 빈칸은 과목 점수들을 합산하여 총점을 구하고, 이를 과목 수로 나누어 평균을 도출한 뒤 결과 서식에 맞추어 출력하는 핵심 목표를 가집니다."
            elif '사칙연산' in eid or 'arithmetic' in eid:
                step1_story = "이 빈칸은 두 입력값 간의 사칙연산(덧셈, 뺄셈, 곱셈, 나눗셈)을 각각 계산하여 결과 변수에 저장하고 지정된 서식에 맞게 출력하는 핵심 목표를 가집니다."
            elif topic == "string_len":
                step1_story = "이 빈칸은 문자열의 길이 및 구성 문자를 점검하여 유효성을 판별하고 결과를 출력하는 핵심 목표를 가집니다."
            elif '스택' in eid or 'stack' in eid or any(f in ('push', 'pop', 'peek') for f in has_func) or 'self.top' in target_str:
                step1_story = "이 빈칸은 스택의 경계 조건을 확인하고, 최상단(top) 데이터를 안전하게 입출력한 뒤 포인터 위치를 갱신하는 핵심 목표를 가집니다."
            elif '큐' in eid or 'queue' in eid or any(f in ('enqueue', 'dequeue') for f in has_func):
                step1_story = "이 빈칸은 큐의 경계 조건을 확인하고, front/rear 포인터를 원형 회전 이동시키며 데이터를 입출력하는 핵심 목표를 가집니다."
            else:
                # 기계적 템플릿 비문을 제거하고 구문 분석 기반의 자연스러운 한국어 목적 문장 생성
                pure_inputs = [v for v in source_vars if v not in target_vars]
                s_desc = f"입력 변수(`{', '.join(pure_inputs[:2])}`)" if pure_inputs else "주어진 변수"
                t_desc = f"결과 변수(`{', '.join(target_vars[:2])}`)" if target_vars else "목표 결과값"
                
                if target_vars and pure_inputs:
                    step1_story = f"이 빈칸은 {s_desc}의 값을 연산식에 대입하여 {t_desc}의 최종 결괏값을 도출하는 핵심 목표를 가집니다."
                elif target_vars:
                    step1_story = f"이 빈칸은 주어진 연산 조건에 맞추어 {t_desc}에 올바른 계산 결과를 완성하는 핵심 목표를 가집니다."
                elif has_if:
                    step1_story = f"이 빈칸은 {s_desc}를 조건식으로 비교 판별하여 프로그램의 분기 흐름을 제어하는 핵심 목표를 가집니다."
                elif has_print:
                    step1_story = f"이 빈칸은 계산된 결괏값을 문제에서 요구한 예시 출력 서식에 맞추어 콘솔에 표시하는 핵심 목표를 가집니다."
                else:
                    step1_story = f"이 빈칸은 주어진 조건에 맞추어 {t_desc}를 계산하고 핵심 알고리즘 로직을 완성하는 목표를 가집니다."

            # [2단계: 변수와 문법 팁 - 사용 도구 점검]
            # 정답 수식은 숨기고, 필요한 변수와 연산자 도구 안내
            var_part = f"다룰 변수(`{', '.join(all_vars[:5])}`)" if all_vars else "관련 변수"
            op_part = f"연산 기호({', '.join(operators)})" if operators else "필요한 연산 기호"
            tips = []
            if has_pow or "**" in target_str:
                tips.append("거듭제곱 ** 연산자(예: `x ** 2`는 x의 2제곱)")
            if has_div or "/" in target_str:
                tips.append("나눗셈 / 연산자(결과는 float 실수)")
            if has_mod or "%" in target_str or "//" in target_str:
                tips.append("정수 몫 // 연산자 또는 나머지 % 연산자")
            if re.search(r'\b(and|or)\b', target_str) or any("논리" in op for op in operators):
                tips.append("논리 연산자 and / or (복합 조건 결합)")
            if has_if or re.search(r'\bif\b', target_str):
                tips.append("조건식 if 선언, 끝의 콜론(:) 및 비교 연산자(==, !=, >, <)")
            if "len" in has_func or "len(" in target_str:
                tips.append("길이 측정 len() 함수")
            if any(f in has_func for f in ("int", "float")):
                tips.append("자료형 변환 함수 int() 또는 float()")
            if any(kw in target_str for kw in ("self.top", "self.rear")):
                tips.append("자료구조 포인터 인스턴스 변수의 증감")

            if tips:
                tip_str = "\n\n💡 [사용 도구 팁]\n" + "\n".join(f"• {t}" for t in tips)
            else:
                tip_str = ""
            step2_story = f"이 처리에 필요한 {var_part}와 {op_part}를 떠올려 준비하세요.{tip_str}"

            # [3단계: 문법 골격 조립 - 정답 코드 노출 방지 추상화 형태]
            # 실제 정답 수치가 아닌 플레이스홀더 [...] 추상 골격으로 안내
            if skeletons:
                step_parts = [f"{i}단계: {s}" for i, s in enumerate(skeletons[:4], 1)]
                step3_story = f"아래와 같은 추상화된 문법 골격 순서로 코드를 완성하세요:\n" + " ➔ ".join(step_parts) + "\n(※ 각 플레이스홀더 `[...]` 자리에 알맞은 변수와 연산자를 직접 채워 넣으세요.)"
                code_mnemonic_3 = " ➔ ".join(skeletons[:3])
            else:
                step3_story = "좌변에 대상 변수명을 두고 대입 연산자(=)를 사용해 우변의 연산식을 완성하세요. (추상 형태: `[결과변수] = [연산식]`)"
                code_mnemonic_3 = "[변수] = [연산식]"

            cloze_steps = [
                {
                    'step_number': 1,
                    'title': '1️⃣ [목적 파악 - 해결할 연산 목표]',
                    'action_story': step1_story,
                    'code_mnemonic': '연산 의도 및 목표 파악'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [변수와 문법 팁 - 사용 도구 점검]',
                    'action_story': step2_story,
                    'code_mnemonic': '변수명 [연산자] 조합 및 팁'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [문법 골격 조립 - 추상화된 형태]',
                    'action_story': step3_story,
                    'code_mnemonic': code_mnemonic_3
                }
            ]
            flow = {
                'flow_title': f'🎬 {exercise_id or "빈칸 채우기"} 3단계 비계 힌트',
                'metaphor': metaphor or '핵심 코드 라인 연상',
                'steps': cloze_steps
            }
        # 2. 풀코딩 모드: 프로그램 전체 구현을 위한 1인칭 행동 흐름(Action Flow: 준비 -> 연산/반복 -> 상태갱신 -> 출력/반환)
        else:
            flow = cls.resolve_mnemonic_flow(exercise_id, target_code, metaphor=metaphor, flow_steps=flow_steps)

        return flow

    @classmethod
    def _practice_hint_result(cls, exercise_id, hint_step, mode, target_code, attempt_count,
                              current_code, client, flow):
        steps = flow['steps']
        total_steps = len(steps)
        step = max(1, min(int(hint_step), total_steps))
        current_step_info = steps[step - 1]

        # 2. 로드맵 상태 생성
        flow_roadmap = [
            {
                'step_number': s['step_number'],
                'title': s['title'],
                'is_current': s['step_number'] == step,
                'is_unlocked': s['step_number'] <= step
            }
            for s in steps
        ]

        # 3. 학생 현재 코드의 AST 문법 검사 (오타 사전 피드백)
        syntax_warning = None
        if current_code and current_code.strip():
            syntax_res = cls.check_ast_syntax(current_code)
            if not syntax_res['is_valid']:
                syntax_warning = syntax_res['error_message']

        # 4. 정답 해금 판단 (마지막 단계 도달 OR 시도 횟수 3회 이상)
        is_strike_out = (step >= total_steps) or (attempt_count >= 3)
        strike_info = cls.check_strike_and_build_ghost_text(
            problem_id=exercise_id,
            attempt_count=attempt_count,
            hints_used=step if is_strike_out else 1,
            answer_code=target_code,
            student_weakness_weight=0.0
        )

        hint_text = (
            f"{current_step_info['title']}\n"
            f"👉 {current_step_info['action_story']}\n"
            f"(연상 코드 힌트: {current_step_info['code_mnemonic']})"
        )

        problem_meta = cls.generate_practice_statement(
            code=target_code or current_code,
            client=client,
            concept_id=exercise_id
        )

        return {
            'exercise_id': exercise_id,
            'mode': mode,
            'title': problem_meta['title'],
            'description': problem_meta['description'],
            'requirements': problem_meta['requirements'],
            'statement_source': problem_meta.get('source', 'rule_fallback'),
            'flow_title': flow['flow_title'],
            'metaphor': flow['metaphor'],
            'current_step': step,
            'hint_step': step,
            'total_steps': total_steps,
            'remaining_steps': max(0, total_steps - step),
            'remaining_hints': max(0, total_steps - step),
            'current_step_info': current_step_info,
            'hint_text': hint_text,
            'flow_roadmap': flow_roadmap,
            'syntax_warning': syntax_warning,
            'can_reveal_answer': strike_info['can_reveal_answer'],
            'ghost_text_payload': strike_info['ghost_text_payload'],
            'student_weakness_weight': 0.0,
            'message': (
                f"{step}단계 [{current_step_info['title']}] 흐름이 열렸습니다."
                + (" (모든 로직 흐름을 확인하여 [정답 보기] 버튼이 활성화되었습니다!)" if strike_info['can_reveal_answer'] else f" (남은 단계: {max(0, total_steps - step)}단계)")
            )
        }




