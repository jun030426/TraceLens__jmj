"""Unit tests for user-function & stdlib-import practice extraction and cloze blank caps."""
import unittest
from types import SimpleNamespace

from lerny.practice_inputs import adapted_programs, numeric_program, numeric_source, stdin_case
from lerny.practice_support import python_blank_template
from rag_mvp.cloze_generator import ClozeGenerator


class PracticeFunctionsAndClozeTests(unittest.TestCase):
    def test_def_header_is_excluded_from_blanks(self):
        self.assertTrue(ClozeGenerator.is_excluded_line("def calc_bmi(weight, height):"))
        self.assertTrue(ClozeGenerator.is_excluded_line("async def fetch_data(x):"))
        self.assertTrue(ClozeGenerator.is_excluded_line("def __init__(self):"))

    def test_user_function_return_loop_augassign_and_call_get_blanks(self):
        code = (
            "def sum_to(n):\n"
            "    total = 0\n"
            "    for i in range(1, n + 1):\n"
            "        total += i\n"
            "    return total\n"
            "n = 5\n"
            "print(sum_to(n))\n"
        )
        blanks = ClozeGenerator.select_blanks(code, protected_lines={5})
        answers = [b["answer"] for b in blanks]
        self.assertIn("for i in range(1, n + 1):", answers)
        self.assertIn("total += i", answers)
        self.assertTrue(all(not a.startswith("def ") for a in answers))
        # 7 code lines -> at most 3 blanks (<= half)
        self.assertLessEqual(len(blanks), 3)

    def test_only_computed_returns_are_eligible_for_automatic_and_model_blanks(self):
        for expr in ("x * 2", "f(x)", "a > b", "a and b", "x if c else y", "-x",
                     "[x for x in items]", "items[i + 1]", "(a, f(x))"):
            with self.subTest(expr=expr):
                line = "return " + expr
                code = "def example(x):\n    " + line
                self.assertEqual([b["answer"] for b in ClozeGenerator.select_blanks(code)], [line])
                self.assertEqual(python_blank_template(code, [1], "")[1], {"1": line})
        for line in ("return", "return total", "return a, b", "return items[0]", 'return "a+b"',
                     "return 5", "return total  # [blank]", "return input()", "return print(x)"):
            with self.subTest(line=line):
                code = "def example(total):\n    " + line
                self.assertEqual(ClozeGenerator.select_blanks(code), [])
                self.assertEqual(python_blank_template(code, [1], ""), (code, {}))

    def test_model_simple_return_is_replaced_with_calculation_or_print_argument(self):
        code = "def scale(x):\n    total = x * 2\n    return total"
        self.assertEqual(python_blank_template(code, [2], "")[1], {"1": "total = x * 2"})
        code = "def identity(x):\n    return x\nprint(identity(2))"
        template, blanks = python_blank_template(code, [1], "")
        self.assertEqual(template, "def identity(x):\n    return x\nprint([[빈칸]])")
        self.assertEqual(blanks, {"1": "identity(2)"})

    def test_recursive_return_keeps_its_high_priority(self):
        code = "def fib(n):\n    other = n * 2\n    return fib(n - 1) + fib(n - 2)"
        blank, = ClozeGenerator.select_blanks(code, max_blanks=1)
        self.assertEqual((blank["line_no"], blank["score"], blank["category"]),
                         (3, 100, "algorithm_recursive_call"))

    def test_multiline_value_return_is_excluded_even_on_a_model_selected_continuation(self):
        code = "def pair(a, b):\n    return (\n        a, b\n    )"
        self.assertEqual(python_blank_template(code, [1, 2], ""), (code, {}))

    def test_adaptation_repairs_or_holds_a_value_only_return(self):
        def adapt(body, tail):
            code = f"def helper(items):\n    {body}\nn = int(input())" + tail
            chunk = SimpleNamespace(id="example", version_id="v", content=f"```python\n{code}\n```", locator={})
            proposal = {"source_id": "example", "title": "연습", "prompt": "함수의 결과를 계산해 출력하세요.",
                        "cases": [[1], [2], [3]], "blank_lines": [2]}
            held = []
            programs = adapted_programs([chunk], lambda *_: {"programs": [proposal]}, held=held)
            return [p.blank_lines for p, _ in programs], held

        self.assertEqual(adapt("return items[0]", "\nresult = n * 2\nprint(result)"), ([[4]], []))
        self.assertEqual(adapt("return items[0]", "\nprint(n * 2)"), ([[4]], []))
        self.assertEqual(adapt("return print(items)", "\nprint(n * 2)"), ([[4]], []))
        self.assertEqual(adapt("return items[n + 1]", "\nprint(n)"), ([[2]], []))
        self.assertEqual(adapt("return items[0]", ""), ([], [{"source_id": "example", "reason": "INVALID_PRACTICE_BLANK"}]))

    def test_short_code_never_blanks_more_than_half_of_lines(self):
        short_fn = (
            "def compute(x):\n"
            "    a = x + 1\n"
            "    b = a * 2\n"
            "    c = b - 3\n"
            "    d = c + 4\n"
        )
        # 5 code lines with 4 equal-tier candidates -> effective_max = 5 // 2 = 2
        blanks = ClozeGenerator.select_blanks(short_fn, max_blanks=4)
        self.assertEqual(len(blanks), 2)
        self.assertTrue(all(not b["answer"].startswith("def ") for b in blanks))

    def test_simple_arithmetic_regression_still_picks_only_calculation(self):
        source = "n = 3\nresult = n * 2\nprint(result)"
        self.assertEqual([b["answer"] for b in ClozeGenerator.select_blanks(source)], ["result = n * 2"])

    def test_numeric_program_allows_leading_stdlib_import_and_rejects_external(self):
        stdlib_code = "import math\nr = float(input())\narea = math.pi * r * r\nprint(f'{area:.2f}')"
        parsed = numeric_program(stdlib_code)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["inputs"], [{"name": "r", "type": "float", "line": 2}])
        self.assertEqual(parsed["import_prefix"], "import math\n")
        self.assertFalse(parsed["has_def"])
        decl, vals = stdin_case(parsed, [3.0])
        self.assertEqual(decl, "r = 3.0")
        self.assertEqual(vals, (3.0,))

        external_code = "import numpy as np\nx = int(input())\nprint(np.array([x]))"
        self.assertIsNone(numeric_program(external_code))

    def test_numeric_program_rejects_nondeterministic_stdlib_imports(self):
        for stmt in (
            "import random",
            "from random import randint",
            "import time",
            "from datetime import datetime",
            "import secrets",
            "import uuid",
        ):
            code = f"{stmt}\nn = int(input())\nprint(n)"
            self.assertIsNone(numeric_program(code), f"should reject {stmt}")

        # Deterministic stdlib imports like collections / itertools still pass
        det_code = "from collections import Counter\ns = input()\nprint(Counter(s))"
        self.assertIsNotNone(numeric_program(det_code))

    def test_numeric_program_allows_leading_user_def_and_builds_safe_full_template(self):
        def_code = (
            "import math\n\n"
            "def circle_area(r):\n"
            "    return math.pi * r * r\n\n"
            "r = float(input())\n"
            "print(f'{circle_area(r):.2f}')"
        )
        parsed = numeric_source(f"```python\n{def_code}\n```")
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["has_def"])
        self.assertEqual(parsed["import_prefix"], "import math\n")
        self.assertEqual(parsed["inputs"], [{"name": "r", "type": "float", "line": 6}])

        chunk = SimpleNamespace(id="c1", version_id="v1", content=f"```python\n{def_code}\n```", locator={})

        def fake_generate(_prompt, _schema):
            return {
                "programs": [
                    {
                        "source_id": "c1",
                        "title": "원 넓이 함수",
                        "prompt": "반지름을 받아 원의 넓이를 구하는 함수를 작성하세요.",
                        "cases": [[1.0], [2.0], [3.0]],
                        "blank_lines": [4],
                    }
                ]
            }

        adapted_list = adapted_programs([chunk], fake_generate)
        self.assertEqual(len(adapted_list), 1)
        prog, quote = adapted_list[0]
        self.assertEqual(quote, def_code)
        self.assertEqual(prog.input_statement, "r = 1.0")
        self.assertEqual(prog.blank_lines, [4])
        # full_template keeps stdlib import + input fixture, NEVER leaks def circle_area body
        self.assertIn("import math\n", prog.full_template)
        self.assertIn("r = 1.0", prog.full_template)
        self.assertNotIn("def circle_area", prog.full_template)
        self.assertNotIn("math.pi * r * r", prog.full_template)
        self.assertLess(len(prog.full_template), len(prog.code))

    def test_leading_comment_and_import_preserved_in_full_template(self):
        code = "# 반지름 입력\nimport math\nr = float(input())\narea = math.pi * r * r\nprint(area)"
        chunk = SimpleNamespace(id="c2", version_id="v1", content=f"```python\n{code}\n```", locator={})
        adapted_list = adapted_programs(
            [chunk],
            lambda *_: {
                "programs": [
                    {
                        "source_id": "c2",
                        "title": "원 넓이",
                        "prompt": "원의 넓이를 계산해 출력하세요.",
                        "cases": [[1.0], [2.0], [3.0]],
                        "blank_lines": [4],
                    }
                ]
            },
        )
        prog, _ = adapted_list[0]
        self.assertTrue(prog.full_template.startswith("# 반지름 입력\nimport math\nr = 1.0"))
        self.assertEqual(prog.blank_lines, [4])

    def test_multiline_function_balances_return_and_calculation_blanks(self):
        code = (
            "def calc_bill(price, qty, rate):\n"
            "    subtotal = price * qty\n"
            "    discount = subtotal * rate\n"
            "    tax = (subtotal - discount) * 0.1\n"
            "    return subtotal - discount + tax\n"
        )
        # 5 code lines -> max 2 blanks (return expression 65pt + non-adjacent calculation 60pt)
        blanks = ClozeGenerator.select_blanks(code, max_blanks=4)
        self.assertEqual(len(blanks), 2)
        self.assertTrue(any(b["answer"].startswith("return ") for b in blanks))


if __name__ == "__main__":
    unittest.main()
