# -*- coding: utf-8 -*-
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
exec(open(os.path.join(os.path.dirname(__file__), 'tracer.py'), encoding='utf-8').read())

def collect(code, max_events=5000):
    chunks = []
    run_traced(code, lambda s: chunks.append(json.loads(s)), max_events)
    events = [e for c in chunks for e in (c if isinstance(c, list) else [])]
    tail = next(c for c in chunks if isinstance(c, dict))
    return events, tail

# 1) aliasing: b=a 이후 두 변수가 같은 objectId
events, tail = collect("a = [1, 2]\nb = a\nb.append(3)\n")
refs = {}
for e in events:
    for d in e['localsDelta']:
        if d['op'] == 'set' and d['value']['k'] == 'ref':
            refs[d['name']] = d['value']['id']
assert refs['a'] == refs['b'], f"aliasing 실패: {refs}"

# 2) mutation: append 후 objectsDelta에 3원소 리스트
snaps = [d['obj'] for e in events for d in e['objectsDelta'] if d['op'] == 'set']
assert any(o['type'] == 'list' and len(o.get('items', [])) == 3 for o in snaps), "mutation 미포착"

# 3) causedByLine 귀속: append(3행)의 효과는 다음 이벤트에서 causedByLine=3
mut_ev = next(e for e in events if any(
    d['op'] == 'set' and d.get('obj', {}).get('id') == refs['a'] and len(d['obj'].get('items', [])) == 3
    for d in e['objectsDelta']))
assert mut_ev['causedByLine'] == 3, f"귀속 실패: {mut_ev['causedByLine']}"

# 4) 함수 호출: frameId 구분과 call/return, stdout
events2, _ = collect("def f(x):\n    return x + 1\nprint(f(1))\n")
kinds = [e['kind'] for e in events2]
assert 'call' in kinds and 'return' in kinds
fids = {e['frameId'] for e in events2 if e['func'] == 'f'}
assert fids and 0 not in fids, f"함수 프레임 id 미구분: {fids}"
assert any('2' in e['stdout'] for e in events2), "stdout 미포착"

# 5) 예외: exception 이벤트 + error 필드
events3, tail3 = collect("arr = [1]\nprint(arr[5])\n")
assert any(e['kind'] == 'exception' for e in events3), "exception 이벤트 없음"
assert tail3.get('error'), "예외 요약 누락"

# 6) 상한: max_events 초과 시 clipped
_, tail4 = collect("i = 0\nwhile True:\n    i += 1\n", max_events=500)
assert tail4['clipped'] is True, "clipped 미설정"

print("tracer_test: ALL PASS")
