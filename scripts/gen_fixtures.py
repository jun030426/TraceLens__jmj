# -*- coding: utf-8 -*-
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(ROOT, 'src', 'trace', 'py', 'tracer.py'), encoding='utf-8').read())

SAMPLES = {
    'aliasing': 'team_a = ["kim", "lee"]\nteam_b = team_a\nteam_b.append("park")\nprint(team_a)\n',
    'loop': 'total = 0\nfor i in range(5):\n    total += i\nprint(total)\n',
}
os.makedirs(os.path.join(ROOT, 'src', 'fixtures'), exist_ok=True)
for name, code in SAMPLES.items():
    chunks = []
    run_traced(code, lambda s: chunks.append(json.loads(s)))
    events = [e for c in chunks for e in (c if isinstance(c, list) else [])]
    tail = next(c for c in chunks if isinstance(c, dict))
    out = {'events': events, 'clipped': tail['clipped'], 'error': tail.get('error')}
    path = os.path.join(ROOT, 'src', 'fixtures', f'{name}.trace.json')
    json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
    print(name, len(events), 'events →', path)
