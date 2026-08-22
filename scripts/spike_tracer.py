# -*- coding: utf-8 -*-
"""Tracer 스파이크 — 기획안 검증 과제 [최우선]
측정: (1) 코드 유형별 이벤트 수·직렬화 크기 폭발 정도
     (2) settrace 트레이서의 실행 오버헤드 (베이스라인 대비)
     (3) sys.monitoring으로 동일한 상태 수집이 가능한가 (frame 접근성) + 오버헤드 비교
"""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(ROOT, 'src', 'trace', 'py', 'tracer.py'), encoding='utf-8').read())

SAMPLES = {
    '버블정렬 n=30': (
        "import random\n"  # noqa — 표준 random은 지원 범위
        "nums = list(range(30, 0, -1))\n"
        "n = len(nums)\n"
        "for i in range(n):\n"
        "    for j in range(n - i - 1):\n"
        "        if nums[j] > nums[j + 1]:\n"
        "            nums[j], nums[j + 1] = nums[j + 1], nums[j]\n"
    ),
    '재귀 fib(15)': (
        "def fib(n):\n"
        "    if n <= 1:\n"
        "        return n\n"
        "    return fib(n - 1) + fib(n - 2)\n"
        "r = fib(15)\n"
    ),
    '루프 1000회 누적': (
        "total = 0\n"
        "log = []\n"
        "for i in range(1000):\n"
        "    total += i\n"
        "    if i % 100 == 0:\n"
        "        log.append(total)\n"
    ),
    '중첩 dict 조작': (
        "db = {}\n"
        "for i in range(100):\n"
        "    key = 'user' + str(i % 10)\n"
        "    if key not in db:\n"
        "        db[key] = {'count': 0, 'items': []}\n"
        "    db[key]['count'] += 1\n"
        "    db[key]['items'].append(i)\n"
    ),
    '대량 리스트 성장': (
        "big = []\n"
        "for i in range(500):\n"
        "    big.append(i * 2)\n"
    ),
}

MAX = 200_000

def bench_settrace(code):
    chunks = []
    t0 = time.perf_counter()
    run_traced(code, lambda s: chunks.append(s), MAX)
    elapsed = time.perf_counter() - t0
    events = sum(len(json.loads(c)) for c in chunks if c.lstrip().startswith('['))
    size = sum(len(c.encode('utf-8')) for c in chunks)
    tail = json.loads(chunks[-1])
    return events, size, elapsed, tail.get('clipped', False)

def bench_baseline(code):
    compiled = compile(code, '<user>', 'exec')
    t0 = time.perf_counter()
    exec(compiled, {})
    return time.perf_counter() - t0

def bench_monitoring(code):
    """sys.monitoring으로 LINE 이벤트 + locals 접근이 가능한지 검증.
    콜백에는 frame이 안 오므로 sys._getframe로 우회 — 이 우회가 성립하는가가 핵심 질문."""
    mon = sys.monitoring
    TOOL = 2  # sys.monitoring.PROFILER_ID 대신 임의 툴 id
    mon.use_tool_id(TOOL, 'spike')
    count = 0
    locals_ok = 0
    def on_line(codeobj, line):
        nonlocal count, locals_ok
        if codeobj.co_filename != '<user>':
            return
        count += 1
        f = sys._getframe(1)          # 콜백 바로 밖 = 사용자 프레임
        if f.f_code is codeobj:
            _ = dict(f.f_locals)       # 상태 스냅샷이 실제로 잡히는가
            locals_ok += 1
    mon.register_callback(TOOL, mon.events.LINE, on_line)
    mon.set_events(TOOL, mon.events.LINE)
    compiled = compile(code, '<user>', 'exec')
    t0 = time.perf_counter()
    try:
        exec(compiled, {})
    finally:
        mon.set_events(TOOL, 0)
        mon.register_callback(TOOL, mon.events.LINE, None)
        mon.free_tool_id(TOOL)
    return count, locals_ok, time.perf_counter() - t0

print(f"Python {sys.version.split()[0]}\n")
print(f"{'샘플':<14} {'이벤트':>8} {'직렬화KB':>9} {'베이스라인':>10} {'settrace':>9} {'배율':>6} {'mon.LINE':>9} {'locals확보':>9} {'mon시간':>8}")
for name, code in SAMPLES.items():
    base = bench_baseline(code)
    ev, size, st_time, clipped = bench_settrace(code)
    mc, mok, mt = bench_monitoring(code)
    clip = ' (클립!)' if clipped else ''
    print(f"{name:<14} {ev:>8,} {size/1024:>8.1f}K {base*1000:>9.2f}ms {st_time*1000:>8.0f}ms {st_time/max(base,1e-9):>5.0f}x {mc:>9,} {mok:>9,} {mt*1000:>7.1f}ms")
