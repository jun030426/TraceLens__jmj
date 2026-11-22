"""Unit tests for ClozeGenerator (Data Structures & Algorithms Blank Selector)."""
import unittest
from rag_mvp.cloze_generator import ClozeGenerator


class TestClozeGenerator(unittest.TestCase):

    def test_data_structure_stack3_blanks(self):
        # Code from stack3.py
        code = '''
def handle_menu(menu, stack):
    if menu == "2":
        if len(stack) > 0:
            book = stack.pop()
            print("반납한 도서:", book)
        else:
            print("반납할 도서가 없습니다.")
'''
        res = ClozeGenerator.generate_cloze_problem(code, min_score=80, max_blanks=2)
        self.assertEqual(res['blank_count'], 2)
        blanks = res['blanks']

        # Label (가) should be len(stack) > 0 (80점 언더플로우 경계 방어)
        self.assertEqual(blanks[0]['label'], '(가)')
        self.assertIn('len(stack) > 0', blanks[0]['answer'])
        self.assertEqual(blanks[0]['category'], 'ds_underflow_check')
        self.assertEqual(blanks[0]['score'], 80)

        # Label (나) should be book = stack.pop() (100점 핵심 연산)
        self.assertEqual(blanks[1]['label'], '(나)')
        self.assertIn('stack.pop()', blanks[1]['answer'])
        self.assertEqual(blanks[1]['category'], 'ds_stack_pop')
        self.assertEqual(blanks[1]['score'], 100)

        # Masked code verification
        self.assertIn('[ (가) ____________________________ ]', res['masked_code'])
        self.assertIn('[ (나) ____________________________ ]', res['masked_code'])
        self.assertNotIn('book = stack.pop()', res['masked_code'])

    def test_algorithm_binary_search_blanks(self):
        # Canonical Binary Search Algorithm
        code = '''
def binary_search(arr, target):
    low = 0
    high = len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
'''
        res = ClozeGenerator.generate_cloze_problem(code, min_score=80, max_blanks=2)
        self.assertEqual(res['blank_count'], 2)
        blanks = res['blanks']

        # Check that loop invariant while low <= high (80점) or mid calc (90점) or low = mid + 1 (90점) are selected
        scores = [b['score'] for b in blanks]
        self.assertTrue(all(s >= 80 for s in scores))
        categories = [b['category'] for b in blanks]
        self.assertTrue(any('binary_search' in c or 'algorithm' in c for c in categories))

    def test_algorithm_sorting_bubble_sort_blanks(self):
        # Canonical Bubble Sort Algorithm
        code = '''
def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr
'''
        res = ClozeGenerator.generate_cloze_problem(code, min_score=80, max_blanks=2)
        self.assertEqual(res['blank_count'], 2)
        blanks = res['blanks']
        self.assertIn('arr[j] > arr[j + 1]', blanks[0]['answer'])
        self.assertIn('arr[j], arr[j + 1] = arr[j + 1], arr[j]', blanks[1]['answer'])

    def test_algorithm_recursion_base_case_blanks(self):
        # Recursive Fibonacci Algorithm
        code = '''
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)
'''
        res = ClozeGenerator.generate_cloze_problem(code, min_score=80, max_blanks=2)
        self.assertEqual(res['blank_count'], 2)
        blanks = res['blanks']
        self.assertIn('if n <= 1:', blanks[0]['answer'])
        self.assertEqual(blanks[0]['score'], 80)
        self.assertIn('fib(n - 1) + fib(n - 2)', blanks[1]['answer'])
        self.assertEqual(blanks[1]['score'], 100)

    def test_exclusion_patterns(self):
        # Ensure print, input, imports are NEVER selected as blanks
        self.assertTrue(ClozeGenerator.is_excluded_line('print("Hello")'))
        self.assertTrue(ClozeGenerator.is_excluded_line('x = input("메뉴: ")'))
        self.assertTrue(ClozeGenerator.is_excluded_line('while True:'))
        self.assertTrue(ClozeGenerator.is_excluded_line('import math'))
        self.assertFalse(ClozeGenerator.is_excluded_line('if len(stack) > 0:'))
        self.assertFalse(ClozeGenerator.is_excluded_line('mid = (low + high) // 2'))

    def test_instructor_manual_override(self):
        code = '''
def custom_algo(x):
    y = x * 2  # [BLANK]
    return y
'''
        res = ClozeGenerator.generate_cloze_problem(code)
        self.assertEqual(res['blank_count'], 1)
        self.assertEqual(res['blanks'][0]['score'], 200)
        self.assertEqual(res['blanks'][0]['category'], 'instructor_manual_override')

    def test_extract_available_helpers_procedural_and_formulas(self):
        code = '''
height = float(input()) / 100
weight = float(input())
bmi = weight / (height ** 2)
print(f"BMI : {bmi:.2f}")
'''
        slide_text = "문제2. BMI 계산 프로그램 (BMI = 몸무게 / (키(m) * 키(m))) 키(cm)와 몸무게를 입력받아 계산"
        helpers_meta = ClozeGenerator.extract_available_helpers(code, slide_text=slide_text)
        guide_text = helpers_meta['helpers_guide_text']
        self.assertIn("BMI", guide_text)
        self.assertIn("단위 변환", guide_text)
        self.assertIn("**", guide_text)
        self.assertIn("/", guide_text)
        self.assertIn(":.2f", guide_text)

        # Full coding problem for procedural script must include helpers and guide
        prob = ClozeGenerator.generate_full_coding_problem(code, slide_text=slide_text)
        self.assertIn("BMI", prob['helpers_guide_text'])
        self.assertIn("단위 변환", prob['helpers_guide_text'])

    def test_infer_problem_statement_bmi_formula_and_units(self):
        code = '''
height = float(input()) / 100
weight = float(input())
bmi = weight / (height ** 2)
'''
        slide_text = "실습5. BMI 계산기 (BMI = weight / (height(m) * height(m)))"
        stmt = ClozeGenerator.infer_problem_statement(code, slide_text=slide_text)
        self.assertIn("BMI", stmt['title'])
        self.assertIn("BMI 계산 공식", stmt['description'])
        self.assertIn("단위", stmt['description'])
        self.assertTrue(any("단위" in r for r in stmt['requirements']))

    def test_cloze_dynamic_syntax_hints(self):
        # 1. No print format clutter in step 2 (print output format belongs to problem description)
        hint_print = ClozeGenerator.get_practice_hint(
            exercise_id="py-arithmetic",
            hint_step=2,
            mode="cloze",
            target_code="print('덧셈 :', a + b)"
        )
        self.assertNotIn("출력 형식 맞추기", hint_print['hint_text'])
        self.assertNotIn("self.top", hint_print['hint_text'])

        # 2. Arithmetic operator syntax cue in step 2
        hint_op = ClozeGenerator.get_practice_hint(
            exercise_id="py-arithmetic",
            hint_step=2,
            mode="cloze",
            target_code="result = a ** 2 / b"
        )
        self.assertIn("거듭제곱 **", hint_op['hint_text'])
        self.assertNotIn("self.top", hint_op['hint_text'])

        # 3. If logical/comparison condition cue in step 2 and abstract skeleton in step 3
        hint_if = ClozeGenerator.get_practice_hint(
            exercise_id="py-condition",
            hint_step=2,
            mode="cloze",
            target_code="if ((value >= 45 and value <= 65) or (value >= 75 and value <= 95)):"
        )
        self.assertIn("논리 연산자", hint_if['hint_text'])
        self.assertIn("조건식 if", hint_if['hint_text'])

        hint_skel = ClozeGenerator.get_practice_hint(
            exercise_id="py-condition",
            hint_step=3,
            mode="cloze",
            target_code="if ((value >= 45 and value <= 65) or (value >= 75 and value <= 95)):"
        )
        self.assertIn("if (([value] >= [상수값] and [value] <= [상수값]) or ([value] >= [상수값] and [value] <= [상수값])):", hint_skel['hint_text'])

    def test_resolve_mnemonic_flow_bmi_and_arithmetic(self):
        flow_bmi = ClozeGenerator.resolve_mnemonic_flow(exercise_id="bmi_calc", target_code="bmi = weight / (height ** 2)")
        self.assertEqual(len(flow_bmi['steps']), 3)
        self.assertIn("단위 변환", flow_bmi['steps'][0]['title'])
        self.assertIn("BMI", flow_bmi['steps'][1]['title'])

        flow_arith = ClozeGenerator.resolve_mnemonic_flow(exercise_id="사칙연산_실습", target_code="a + b")
        self.assertEqual(len(flow_arith['steps']), 3)
        self.assertIn("사칙연산", flow_arith['steps'][1]['title'])

    def test_dynamic_action_flow_zero_spoiler(self):
        code = '''
value = 50.0
if ((value >= 45 and value <= 65) or (value >= 75 and value <= 95)):
    result = "통과"
else:
    result = "재검사"
print(f"검사할 수치값은 [{value}]이고, 결과는 [{result}] 입니다.")
'''
        flow = ClozeGenerator.generate_dynamic_action_flow(code, title="수치 판별")
        for s in flow['steps']:
            # Exact constants must not be spoiled in action_story
            self.assertNotIn("45", s['action_story'])
            self.assertNotIn("65", s['action_story'])
            self.assertNotIn("75", s['action_story'])
            self.assertNotIn("95", s['action_story'])
            # Constants must be masked as [상수값] in code_mnemonic
            if "if" in s['code_mnemonic']:
                self.assertIn("[상수값]", s['code_mnemonic'])
                self.assertNotIn("45", s['code_mnemonic'])


if __name__ == '__main__':
    unittest.main()
