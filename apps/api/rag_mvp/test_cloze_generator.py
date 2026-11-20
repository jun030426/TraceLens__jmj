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

        # Label (가) should be len(stack) > 0 (100점 언더플로우 검사)
        self.assertEqual(blanks[0]['label'], '(가)')
        self.assertIn('len(stack) > 0', blanks[0]['answer'])
        self.assertEqual(blanks[0]['category'], 'ds_underflow_check')
        self.assertEqual(blanks[0]['score'], 100)

        # Label (나) should be book = stack.pop() (80점 pop 연산)
        self.assertEqual(blanks[1]['label'], '(나)')
        self.assertIn('stack.pop()', blanks[1]['answer'])
        self.assertEqual(blanks[1]['category'], 'ds_stack_pop')
        self.assertEqual(blanks[1]['score'], 80)

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

        # Check that loop invariant while low <= high (100점) or mid calc (90점) or low = mid + 1 (90점) are selected
        scores = [b['score'] for b in blanks]
        self.assertTrue(all(s >= 90 for s in scores))
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
        self.assertEqual(blanks[0]['score'], 100)
        self.assertIn('fib(n - 1) + fib(n - 2)', blanks[1]['answer'])
        self.assertEqual(blanks[1]['score'], 90)

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


if __name__ == '__main__':
    unittest.main()
