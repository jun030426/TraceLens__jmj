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

# 7) __main__ 가드: AI 생성 스크립트에 흔한 패턴이 건너뛰어지면 안 됨
events5, _ = collect("def main():\n    print('ran')\n\nif __name__ == '__main__':\n    main()\n")
assert any('ran' in e['stdout'] for e in events5), "__main__ 가드 블록이 실행되지 않음"

# 8) deque: 시퀀스로 직렬화 (BFS 큐가 미지원 상자로 남으면 안 됨)
events6, _ = collect("from collections import deque\nq = deque()\nq.append((1, 2))\nprint(len(q))\n")
dq = [o for e in events6 for d in e['objectsDelta']
      if d['op'] == 'set' and d.get('obj', {}).get('type') == 'deque'
      for o in [d['obj']]]
assert dq, "deque ObjectSnap 없음"
assert any(len(o.get('items', [])) == 1 for o in dq), "deque items 미직렬화"

# 9) 반환값: return 이벤트가 returned를 싣는다 (sys.settrace의 arg — 재귀 unwind를 그리는 사실)
events7, _ = collect("""def fact(n):
    if n <= 1:
        return 1
    return n * fact(n - 1)
r = fact(4)
""")
rets = [e['returned'] for e in events7 if e['kind'] == 'return' and 'returned' in e]
assert [v['v'] for v in rets] == ['1', '2', '6', '24'], f"반환값 미포착: {rets}"

# 10) 컨테이너 반환: ref로 실리고 같은 레지스트리에서 해석된다
events8, _ = collect("""def make():
    return [1, 2, 3]
xs = make()
""")
ret8 = next(e for e in events8 if e['kind'] == 'return' and 'returned' in e)
assert ret8['returned']['k'] == 'ref', f"컨테이너 반환이 ref가 아님: {ret8['returned']}"
oid = ret8['returned']['id']
assert any(d.get('obj', {}).get('id') == oid and len(d['obj'].get('items', [])) == 3
           for e in events8 for d in e['objectsDelta']), "반환 객체 스냅이 없다"

# 11) None은 싣지 않는다 — 암묵 반환과 `return None`은 구분되지 않고 가르치는 게 없다
events9, _ = collect("""def show():
    print('hi')
show()
""")
assert not any('returned' in e for e in events9 if e['kind'] == 'return'), "None 반환이 실렸다"

# 12) 예외 unwind는 침묵 — arg가 None이라 `return None`과 구분되지 않는다 (없는 반환을 지어내지 않는다)
events10, _ = collect("""def boom(n):
    return n / 0
try:
    boom(1)
except ZeroDivisionError:
    pass
""")
boom_ret = [e for e in events10 if e['kind'] == 'return' and e['func'] == 'boom']
assert boom_ret and not any('returned' in e for e in boom_ret), f"예외 unwind에 반환값이 실렸다: {boom_ret}"

# 13) 예외를 그 프레임에서 잡으면 이후의 정상 반환은 실린다 (플래그가 line에서 지워진다)
events11, _ = collect("""def caught(n):
    try:
        return n / 0
    except ZeroDivisionError:
        return -1
r = caught(5)
""")
cr = [e['returned'] for e in events11 if e['kind'] == 'return' and e['func'] == 'caught' and 'returned' in e]
assert [v['v'] for v in cr] == ['-1'], f"잡힌 예외 뒤 반환값 누락: {cr}"

print("tracer_test: ALL PASS")
