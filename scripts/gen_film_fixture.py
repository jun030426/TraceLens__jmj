# -*- coding: utf-8 -*-
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(ROOT, 'src', 'trace', 'py', 'tracer.py'), encoding='utf-8').read())

CODE = '''def build_squares(n):
    out = []
    for i in range(n):
        out.append(i * i)
    return out


def total_of(values):
    if not values:
        return 0
    return values[0] + total_of(values[1:])


def label_for(score):
    if score >= 200:
        return "high"
    if score >= 50:
        return "mid"
    return "low"


squares = build_squares(12)
print("squares:", squares)

shared = squares
shared.append(999)
print("aliased:", squares[-1])

head = squares[:4]
score = total_of(head)
print("score:", score)

grade = label_for(score)
print("grade:", grade)

table = {}
for name in ["a", "b", "c"]:
    table[name] = len(name) * score
print("table:", table)
'''

chunks = []
run_traced(CODE, lambda s: chunks.append(json.loads(s)), 20000)
events = [e for c in chunks for e in (c if isinstance(c, list) else [])]
tail = next(c for c in chunks if isinstance(c, dict))
out = {'events': events, 'clipped': tail['clipped'], 'error': tail.get('error'), 'code': CODE}
path = os.path.join(ROOT, 'src', 'fixtures', 'film-demo.trace.json')
json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
print('events:', len(events), '->', path)
