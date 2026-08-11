# -*- coding: utf-8 -*-
"""기술 벤치마크 샘플 셋 생성 — 기획안 검증 과제 '유형별 층화'.
각 샘플을 (1) 순수 실행해 기대 stdout 확보 (2) 트레이서로 실행해 트레이스 확보.
산출: src/bench/fixtures/<id>.bench.json = { category, code, expectedStdout, expectedError, events, clipped }
"""
import json, os, sys, io, contextlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(ROOT, 'src', 'trace', 'py', 'tracer.py'), encoding='utf-8').read())

SAMPLES = [
    ('control-if', '제어 흐름', "score = 85\nif score >= 90:\n    grade = 'A'\nelif score >= 80:\n    grade = 'B'\nelse:\n    grade = 'C'\nprint(grade)\n"),
    ('control-while', '제어 흐름', "n = 5\nwhile n > 0:\n    n -= 1\nprint(n)\n"),
    ('function-basic', '함수', "def add(a, b):\n    return a + b\n\nresult = add(3, 4)\nprint(result)\n"),
    ('function-nested', '함수', "def double(x):\n    return x * 2\n\ndef quad(x):\n    return double(double(x))\n\nprint(quad(3))\n"),
    ('recursion-fact', '재귀', "def fact(n):\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n\nprint(fact(5))\n"),
    ('recursion-sum', '재귀', "def total(items):\n    if not items:\n        return 0\n    return items[0] + total(items[1:])\n\nprint(total([1, 2, 3, 4]))\n"),
    ('mutation-list', 'mutation', "stack = []\nstack.append(1)\nstack.append(2)\ntop = stack.pop()\nprint(top, stack)\n"),
    ('mutation-dict', 'mutation', "scores = {'kim': 80}\nscores['lee'] = 90\nscores['kim'] += 5\nprint(scores)\n"),
    ('aliasing-basic', 'aliasing', "a = [1, 2]\nb = a\nb.append(3)\nprint(a)\n"),
    ('aliasing-nested', 'aliasing', "grid = [[0, 0]] * 2\ngrid[0][0] = 7\nprint(grid)\n"),
    ('nested-data', '중첩 데이터', "users = {'kim': {'age': 20, 'tags': ['a']}}\nusers['kim']['tags'].append('b')\nusers['kim']['age'] += 1\nprint(users)\n"),
    ('nested-list', '중첩 데이터', "matrix = [[1, 2], [3, 4]]\nmatrix[1].append(5)\nprint(matrix)\n"),
    ('exception-index', '예외', "arr = [1, 2]\nprint(arr[5])\n"),
    ('exception-key', '예외', "d = {'a': 1}\nprint(d['b'])\n"),
    ('class-basic', '클래스', "class Point:\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y\n\np = Point(1, 2)\np.x = 10\nprint(p.x, p.y)\n"),
    ('class-method', '클래스', "class Counter:\n    def __init__(self):\n        self.n = 0\n    def tick(self):\n        self.n += 1\n\nc = Counter()\nc.tick()\nc.tick()\nprint(c.n)\n"),
    ('comprehension-list', '컴프리헨션', "nums = [1, 2, 3, 4]\nsquares = [x * x for x in nums]\nprint(squares)\n"),
    ('comprehension-dict', '컴프리헨션', "words = ['a', 'bb', 'ccc']\nlengths = {w: len(w) for w in words}\nprint(lengths)\n"),
]

OUT = os.path.join(ROOT, 'src', 'bench', 'fixtures')
os.makedirs(OUT, exist_ok=True)

for sid, category, code in SAMPLES:
    # (1) 순수 실행 — 기대 stdout·에러
    buf = io.StringIO()
    expected_error = None
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, '<expected>', 'exec'), {})
    except BaseException as e:
        expected_error = f"{type(e).__name__}"
    expected_stdout = buf.getvalue()

    # (2) 트레이서 실행
    chunks = []
    run_traced(code, lambda s: chunks.append(json.loads(s)))
    events = [e for c in chunks for e in (c if isinstance(c, list) else [])]
    tail = next(c for c in chunks if isinstance(c, dict))

    out = {
        'id': sid, 'category': category, 'code': code,
        'expectedStdout': expected_stdout, 'expectedError': expected_error,
        'events': events, 'clipped': tail['clipped'], 'traceError': tail.get('error'),
    }
    json.dump(out, open(os.path.join(OUT, f'{sid}.bench.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(f"{sid:<20} {category:<8} events={len(events):>5}")

print(f"\n{len(SAMPLES)}개 샘플 생성 완료 → {OUT}")
