"""Specialized Cloze / Blank-Filling Generator for Data Structures & Algorithms.

Analyzes Python lecture and lab code to automatically identify critical pedagogical
algorithmic and data structure points for fill-in-the-blank code practice.
"""
import ast
import re


# Specialized Data Structures & Algorithms Scoring Rules
# (Category, Regex Pattern, Score, Category Type)
DSA_RULES = [
    # =========================================================================
    # 1. 100점 구간: 알고리즘 기저 조건(Base Case) & 자료구조 엣지케이스(Edge Case)
    # =========================================================================
    # Algorithm Base Cases (탈출 조건)
    (r'if\s+(?:n|depth|cnt|count|k)\s*(?:<=|==)\s*(?:0|1|\w+)\s*:', 100, 'algorithm_base_case'),
    (r'if\s+(?:low|start|left)\s*>\s*(?:high|end|right)\s*:', 100, 'algorithm_base_case'),
    (r'if\s+(?:not\s+(?:node|root|curr|head)|(?:node|root|curr|head)\s+is\s+None)\s*:', 100, 'algorithm_base_case'),
    (r'while\s+(?:low|left|start)\s*<=\s*(?:high|right|end)\s*:', 100, 'algorithm_loop_invariant'),

    # Data Structure Boundary & State Checks (언더플로우/오버플로우/공백/포화)
    (r'if\s+(?:len\(\w+\)\s*(?:<=|==)\s*0|not\s+\w+|\w+\.is_empty\(\)|self\.top\s*==\s*-1|self\.top\s*<\s*0)', 100, 'ds_underflow_check'),
    (r'if\s+len\(\w+\)\s*>\s*0\s*:', 100, 'ds_underflow_check'),
    (r'if\s+(?:len\(\w+\)\s*(?:>=|==)\s*(?:self\.)?capacity|\w+\.is_full\(\)|self\.top\s*(?:>=|==)\s*(?:self\.)?capacity\s*-\s*1)', 100, 'ds_overflow_check'),
    (r'if\s+\(.*?rear\s*\+\s*1\)\s*%\s*\w+\s*==\s*.*?front', 100, 'ds_circular_queue_full_check'),

    # =========================================================================
    # 2. 90점 구간: 알고리즘 점화식/분할/범위 갱신 & 자료구조 인덱스/포인터 조작
    # =========================================================================
    # Algorithm Key Arithmetic, Divide & Conquer, DP Transitions
    (r'(?:mid|pivot_idx)\s*=\s*\(.*?\)\s*//\s*2', 90, 'algorithm_binary_search_mid'),
    (r'(?:low|left)\s*=\s*mid\s*\+\s*1', 90, 'algorithm_binary_search_pointer'),
    (r'(?:high|right)\s*=\s*mid\s*-\s*1', 90, 'algorithm_binary_search_pointer'),
    (r'dp\[.*?\]\s*=\s*(?:max|min|\w+)\s*\(.*?\)', 90, 'algorithm_dp_transition'),
    (r'return\s+\w+\(.*?-\s*1\)\s*\+\s*\w+\(.*?-\s*2\)', 90, 'algorithm_recursive_call'),
    (r'mid\s*=\s*len\(\w+\)\s*//\s*2', 90, 'algorithm_merge_sort_split'),

    # Data Structure Pointer Mutation & Link Rewiring
    (r'self\.(?:top|front|rear)\s*(?:\+=|-=)\s*1', 90, 'ds_pointer_mutation'),
    (r'self\.(?:front|rear)\s*=\s*\(.*?\)\s*%\s*\w+', 90, 'ds_circular_queue_advance'),
    (r'(?:new_node|node)\.next\s*=\s*(?:self\.)?head', 90, 'ds_linked_list_insert_front'),
    (r'(?:self\.)?head\s*=\s*(?:new_node|node)', 90, 'ds_linked_list_head_update'),
    (r'curr\s*=\s*curr\.next', 90, 'ds_linked_list_traverse'),

    # =========================================================================
    # 3. 80점 구간: 알고리즘 분기 조건/스왑 & 자료구조 핵심 연산 호출
    # =========================================================================
    # Algorithm Branch Conditions, Swaps, Relaxation
    (r'if\s+\w+\[j\]\s*>\s*\w+\[j\s*\+\s*1\]\s*:', 80, 'algorithm_bubble_sort_cmp'),
    (r'\w+\[.*?\],\s*\w+\[.*?\]\s*=\s*\w+\[.*?\],\s*\w+\[.*?\]', 80, 'algorithm_swap'),
    (r'if\s+(?:cost|new_dist|d)\s*<\s*(?:distance|dist)\[.*?\]\s*:', 80, 'algorithm_dijkstra_relaxation'),
    (r'if\s+\w+\s+(?:not\s+in|in)\s+visited\s*:', 80, 'algorithm_visited_check'),
    (r'if\s+target\s*(?:==|<|>)\s*\w+\[mid\]\s*:', 80, 'algorithm_binary_search_cmp'),

    # Data Structure Primary Operation Calls
    (r'(?:\w+\s*=\s*)?\w+\.pop\(\s*\)', 80, 'ds_stack_pop'),
    (r'(?:\w+\s*=\s*)?\w+\.pop\(\s*0\s*\)', 80, 'ds_queue_dequeue'),
    (r'(?:\w+\s*=\s*)?\w+\.popleft\(\s*\)', 80, 'ds_deque_popleft'),
    (r'heapq\.heappop\(.*?\)', 80, 'ds_heap_pop'),
    (r'heapq\.heappush\(.*?\)', 80, 'ds_heap_push'),
    (r'\w+\.append\(.*?\)', 75, 'ds_push_or_enqueue')
]

# Exclusion Blacklist Patterns (Do NOT blank these lines)
EXCLUSION_PATTERNS = [
    r'\bprint\s*\(',
    r'\binput\s*\(',
    r'^\s*while\s+True\s*:',
    r'^\s*break\s*$',
    r'^\s*continue\s*$',
    r'^\s*import\s+',
    r'^\s*from\s+',
    r'^\s*pass\s*$',
    r'^\s*class\s+',
    r'^\s*def\s+__init__'
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
    def select_blanks(cls, code, min_score=80, max_blanks=2):
        """Select top 1~3 critical DSA lines from code as cloze blanks."""
        lines = code.splitlines()
        candidates = []

        for idx, line in enumerate(lines):
            score, category = cls.score_line(line)
            if score >= min_score:
                indent_len = len(line) - len(line.lstrip())
                candidates.append({
                    'line_index': idx,
                    'line_no': idx + 1,
                    'raw_line': line,
                    'answer': line.strip(),
                    'indentation': ' ' * indent_len,
                    'score': score,
                    'category': category
                })

        if not candidates:
            # Fallback to lower threshold (70) if no candidates met 80
            for idx, line in enumerate(lines):
                score, category = cls.score_line(line)
                if 70 <= score < min_score:
                    indent_len = len(line) - len(line.lstrip())
                    candidates.append({
                        'line_index': idx,
                        'line_no': idx + 1,
                        'raw_line': line,
                        'answer': line.strip(),
                        'indentation': ' ' * indent_len,
                        'score': score,
                        'category': category
                    })

        # Sort by score descending, then line order ascending
        candidates.sort(key=lambda x: (-x['score'], x['line_no']))

        # Ensure blanks are not on consecutive lines if possible
        chosen = []
        chosen_line_indices = set()
        for cand in candidates:
            idx = cand['line_index']
            # Allow at most max_blanks
            if len(chosen) >= max_blanks:
                break
            # Prefer non-adjacent lines for readability
            if len(candidates) > max_blanks and any(abs(idx - c_idx) <= 1 for c_idx in chosen_line_indices):
                continue
            chosen.append(cand)
            chosen_line_indices.add(idx)

        # If not enough non-adjacent candidates, take next highest
        if len(chosen) < min(max_blanks, len(candidates)):
            for cand in candidates:
                if len(chosen) >= max_blanks:
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
                'description': '키(height)와 몸무게(weight)를 입력받아 체질량지수(BMI)를 계산하는 프로그램입니다. BMI 계산 공식은 (몸무게(kg) / (키(m) * 키(m)))이며, cm 단위 입력값을 m 단위로 변환한 뒤 소수점 둘째 자리까지 출력해야 합니다.',
                'requirements': [
                    '입력받은 키(cm)를 100으로 나누어 미터(m) 단위로 변환해야 합니다.',
                    'BMI 공식(weight / (height ** 2))을 적용하여 계산해야 합니다.',
                    '소수점 둘째 자리까지 출력 형식(예: BMI : 22.49)을 맞춰야 합니다.'
                ]
            },
            'arithmetic': {
                'title': '사칙연산 프로그램 구현하기',
                'description': '두 수(a, b)를 입력받아 덧셈, 뺄셈, 곱셈, 나눗셈 결과를 각각 계산하고 형식에 맞춰 출력하는 프로그램입니다.',
                'requirements': [
                    '두 수의 덧셈(+), 뺄셈(-), 곱셈(*), 나눗셈(/)을 올바르게 계산해야 합니다.',
                    '나눗셈 결과는 실수(float) 형태로 출력되어야 합니다.',
                    '출력 형식의 콜론(:)과 띄어쓰기를 예시 출력과 동일하게 맞춰야 합니다.'
                ]
            },
            'email': {
                'title': '이메일 유효성 및 문자열 분석 프로그램',
                'description': '이메일 주소 문자열을 분석하여 특수문자(@)의 포함 여부와 전체 길이를 확인하는 프로그램입니다.',
                'requirements': [
                    '문자열의 길이를 len() 함수를 통해 계산해야 합니다.',
                    '문자열 내 @ 기호의 존재 여부를 in 연산자로 확인해야 합니다.'
                ]
            },
            'average': {
                'title': '성적 합계 및 평균 계산 프로그램',
                'description': '여러 점수의 합계와 평균을 계산하여 출력하는 프로그램입니다.',
                'requirements': [
                    '모든 점수의 합계를 누적하여 계산해야 합니다.',
                    '합계를 점수 개수로 나누어 평균을 계산해야 합니다.'
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

        gen_reqs = requirements if requirements is not None else [
            '함수의 입출력 조건과 기저 조건을 올바르게 처리해야 합니다.',
            '파이썬 표준 문법과 인덴트(들여쓰기) 규칙을 준수해야 합니다.'
        ]

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
                    "3. requirements: List of 2~3 concrete technical requirements (e.g., unit conversion, formula calculation, float formatting with :.2f).\n"
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
                    'code_mnemonic': 'if self.is_empty(): return None'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [손에 쥐기 - 떨어뜨리지 않게 보관]',
                    'action_story': '맨 위 과자를 잡았습니다. 통의 번호표를 바꾸기 전, 손(임시 변수)에 먼저 안전하게 쥐고 있어야 과자가 사라지지 않아요!',
                    'code_mnemonic': 'item = self.items[self.top]'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [높이 낮추기 - 맨 위 위치 갱신]',
                    'action_story': '과자를 하나 꺼냈으니, 통 안에 남아있는 가장 위 과자의 번호표(top)를 한 칸 아래로 내려줍니다.',
                    'code_mnemonic': 'self.top -= 1'
                },
                {
                    'step_number': 4,
                    'title': '4️⃣ [건네주기 - 꺼낸 과자 맛있게 반환]',
                    'action_story': '이제 2단계에서 손에 쥐어두었던 과자를 호출자에게 return으로 건네주며 연산을 마칩니다.',
                    'code_mnemonic': 'return item'
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
                    'code_mnemonic': 'if self.is_full(): raise IndexError("Stack Overflow")'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [자리 만들기 - 맨 위 번호표 올리기]',
                    'action_story': '새 과자가 들어갈 윗자리 번호표를 하나 늘립니다.',
                    'code_mnemonic': 'self.top += 1'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [과자 안착 - 새 자리에 쏙 넣기]',
                    'action_story': '새로 준비된 top 위치에 새 과자를 안전하게 내려놓습니다.',
                    'code_mnemonic': 'self.items[self.top] = item'
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
                    'action_story': '내 바로 앞자리((rear + 1) % capacity)에 이미 다른 손님(front)이 앉아있다면 만석(Full)입니다!',
                    'code_mnemonic': 'if (self.rear + 1) % capacity == self.front: raise IndexError("Queue Full")'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [레일 회전 - 시계처럼 한 칸 돌리기]',
                    'action_story': '배열 끝에 닿으면 다시 맨 앞(0번)으로 돌아와야 하므로 % 연산으로 시계처럼 한 칸 돌립니다.',
                    'code_mnemonic': 'self.rear = (self.rear + 1) % capacity'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [접시 놓기 - 새로 이동한 자리에 저장]',
                    'action_story': '새로 이동한 rear 자리에 손님이 가져온 데이터를 내려놓습니다.',
                    'code_mnemonic': 'self.items[self.rear] = item'
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
                    'code_mnemonic': 'low, high = 0, len(arr) - 1'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [깃발 엇갈림 검사 루프]',
                    'action_story': '두 깃발이 서로 지나치지 않는 동안(low <= high) 계속 탐색을 반복합니다.',
                    'code_mnemonic': 'while low <= high:'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [정중앙 찌르기]',
                    'action_story': '가장 확률이 높은 딱 정가운데 위치(mid)를 계산하여 비교합니다.',
                    'code_mnemonic': 'mid = (low + high) // 2'
                },
                {
                    'step_number': 4,
                    'title': '4️⃣ [절반 버리기 (업? 다운?)]',
                    'action_story': '목표값이 더 크면 왼쪽 절반은 쳐다볼 필요도 없으니 왼쪽 깃발을 옮깁니다.',
                    'code_mnemonic': 'low = mid + 1 또는 high = mid - 1'
                },
                {
                    'step_number': 5,
                    'title': '5️⃣ [포기하고 돌아가기]',
                    'action_story': '두 깃발이 엇갈릴 때까지 못 찾았으면 목록에 없다는 뜻이므로 -1을 반환합니다.',
                    'code_mnemonic': 'return -1'
                }
            ]
        },
        'bmi': {
            'flow_title': '🎬 BMI 계산을 완성하는 3단계 행동 흐름',
            'metaphor': '단위를 맞추고 공식에 대입하여 체질량지수 계산하기',
            'steps': [
                {
                    'step_number': 1,
                    'title': '1️⃣ [단위 변환 - cm를 m로]',
                    'action_story': '입력받은 키(height)는 cm 단위입니다. BMI 공식에 대입하기 위해 먼저 100으로 나누어 미터(m) 단위로 변환하세요.',
                    'code_mnemonic': 'height = height / 100'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [BMI 공식 계산]',
                    'action_story': '몸무게(weight)를 키의 제곱(height ** 2)으로 나누어 bmi 변수에 저장하세요.',
                    'code_mnemonic': 'bmi = weight / (height ** 2)'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [소수점 둘째 자리 출력]',
                    'action_story': "f-string의 :.2f 서식을 활용하여 'BMI : 22.49' 형식으로 결과를 출력하세요.",
                    'code_mnemonic': "print(f'BMI : {bmi:.2f}')"
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
                    'action_story': '계산 대상이 되는 두 변수 a와 b의 값을 확인하고 준비합니다.',
                    'code_mnemonic': 'a, b = 10, 5'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [사칙연산 수행]',
                    'action_story': '덧셈(+), 뺄셈(-), 곱셈(*), 나눗셈(/) 연산자를 적용하여 각 연산을 계산합니다. (나눗셈은 실수 float로 계산됩니다)',
                    'code_mnemonic': 'a + b, a - b, a * b, a / b'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [형식에 맞춘 출력]',
                    'action_story': "예시 출력 형식에 맞추어 콜론(:)과 공백을 지키며 print() 함수로 결과를 출력하세요.",
                    'code_mnemonic': "print('덧셈 :', a + b, ...)"
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
                    'code_mnemonic': 'text = ...'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [len() 함수 적용]',
                    'action_story': '공백과 특수문자를 포함한 모든 글자의 개수를 len() 함수로 구합니다.',
                    'code_mnemonic': 'length = len(text)'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [결과 출력]',
                    'action_story': '계산된 글자 수를 요구된 형식에 맞춰 출력합니다.',
                    'code_mnemonic': 'print(length)'
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
                'code_mnemonic': 'if self.is_empty():'
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
                'code_mnemonic': 'self.top -= 1'
            },
            {
                'step_number': 4,
                'title': '4️⃣ [결과 건네주기 - 최종 반환]',
                'action_story': '준비된 결과값을 호출한 곳으로 return하며 함수를 완성합니다.',
                'code_mnemonic': 'return item'
            }
        ]
    }

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
        elif 'binary_search' in eid or 'binary_search' in tcode or 'mid' in tcode:
            matched_key = 'binary_search'
        elif 'bmi' in eid or 'bmi' in tcode or ('height' in tcode and 'weight' in tcode):
            matched_key = 'bmi'
        elif '사칙연산' in eid or 'arithmetic' in eid or ('덧셈' in tcode and '나눗셈' in tcode):
            matched_key = 'arithmetic'
        elif 'email' in eid or 'len' in eid or 'string' in eid or 'len(' in tcode:
            matched_key = 'string_len'

        base = cls.MNEMONIC_FLOW_CATALOG.get(matched_key, cls.GENERIC_ACTION_FLOW)
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
    def practice_hint_flow(cls, exercise_id, mode, target_code, metaphor=None, flow_steps=None):
        # 빈칸 모드의 세 단계와 풀코딩 행동 흐름을 웹 API와 엔진에서 함께 사용한다.
        if mode == 'cloze':
            step1_story = "이 빈칸은 프로그램의 핵심 처리 단계 중 하나입니다. 전체 실행 흐름에서 이 줄이 계산해야 할 목표가 무엇인지 먼저 파악하세요."
            step2_story = "이 처리에 필요한 입력 변수들과 연산 기호를 떠올려 보세요."
            step3_story = "문법 규칙과 들여쓰기에 맞게 코드를 완성하세요. 정답을 직접 타이핑하여 검증받아야 합니다."

            # 문법 특성에 따른 마이크로 팁 자동 부착
            target_str = target_code or ''
            if "print(" in target_str:
                step2_story += " (💡 팁: 출력 결과를 맞출 때는 print('라벨 :', 변수) 또는 f-string 포맷 형식을 점검하세요.)"
            elif any(op in target_str for op in ["**", "/", "//", "%"]):
                step2_story += " (💡 팁: 필요한 수학 연산자(거듭제곱 **, 나눗셈 /, 나머지 %)를 점검하세요.)"
            elif any(fn in target_str for fn in ["int(", "float("]):
                step2_story += " (💡 팁: 숫자의 형태를 바꾸는 자료형 변환 int() 또는 float() 함수를 점검하세요.)"
            elif any(kw in target_str for kw in ["if ", "elif "]):
                step2_story += " (💡 팁: 조건 비교 연산자(==, !=, >, <)와 판별 기준값을 점검하세요.)"
            elif any(kw in target_str for kw in ["self.top", "self.rear", "self.head"]):
                step2_story += " (💡 팁: 자료구조 포인터 인스턴스 변수(top, rear 등)의 위치 증감을 점검하세요.)"

            cloze_steps = [
                {
                    'step_number': 1,
                    'title': '1️⃣ [목적 파악 - 이 줄의 역할]',
                    'action_story': step1_story,
                    'code_mnemonic': '연산 의도 파악'
                },
                {
                    'step_number': 2,
                    'title': '2️⃣ [변수와 연산자 조합]',
                    'action_story': step2_story,
                    'code_mnemonic': '변수명 [연산자] 조합'
                },
                {
                    'step_number': 3,
                    'title': '3️⃣ [문법 완성 및 제출]',
                    'action_story': step3_story,
                    'code_mnemonic': '완성 코드 타이핑'
                }
            ]
            flow = {
                'flow_title': '🎬 빈칸 채우기 핵심 포인트 가이드',
                'metaphor': metaphor or '핵심 코드 라인 연상',
                'steps': cloze_steps
            }
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




