# -*- coding: utf-8 -*-
"""파일럿 설문용 데모 트레이스를 미리 구워둔다.
설문 참가자가 Pyodide 로딩(수 초)을 기다리지 않도록 실행 기록을 정적 파일로 만든다.
각 데모는 '메모리에서 어떤 순서로 진행되는가'만 보여주는 것이 목적이다."""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(ROOT, 'src', 'trace', 'py', 'tracer.py'), encoding='utf-8').read())

DEMOS = [
    ('fill', '''numbers = []
for i in range(8):
    numbers.append(i * 2)
'''),
    ('alias', '''first = ["kim", "lee"]
second = first
second.append("park")
'''),
    ('copy-vs-alias', '''base = [1, 2, 3]
linked = base
copied = base[:]
linked.append(99)
copied.append(-1)
'''),
    ('call', '''def double(value):
    doubled = value * 2
    return doubled


start = 7
result = double(start)
'''),
    ('recursion', '''def countdown(n):
    if n == 0:
        return 0
    return n + countdown(n - 1)


total = countdown(4)
'''),
    ('dict-fill', '''ages = {}
for name in ["kim", "lee", "park", "choi"]:
    ages[name] = len(name)
'''),
]

OUT = os.path.join(ROOT, 'src', 'fixtures', 'demo')
os.makedirs(OUT, exist_ok=True)
for demo_id, code in DEMOS:
    chunks = []
    run_traced(code, lambda s: chunks.append(json.loads(s)), 20000)
    events = [e for c in chunks for e in (c if isinstance(c, list) else [])]
    tail = next(c for c in chunks if isinstance(c, dict))
    payload = {'id': demo_id, 'code': code, 'events': events, 'clipped': tail['clipped']}
    json.dump(payload, open(os.path.join(OUT, f'{demo_id}.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'{demo_id:<14} events={len(events):>4}')
print(f'\n{len(DEMOS)}개 데모 -> {OUT}')
