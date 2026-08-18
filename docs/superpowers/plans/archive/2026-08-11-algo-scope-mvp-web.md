# Algo-Scope MVP 웹 (Slice 0~1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 코드를 붙여넣으면 브라우저 안에서 실제로 실행·추적하고, 규칙 기반 대본으로 자동 재생 무비(챕터·자막·일시정지 인스펙터)를 보여주는 웹 앱 — LLM 없이 E2E 완주 (기획안 Slice 1).

**Architecture:** 4단계 파이프라인 중 ①Tracer(Pyodide Web Worker + sys.settrace) → ②′규칙 기반 대본 생성기(폴백 생성기 = MVP 기본 경로) → ④Player(SVG + GSAP, semantic timeline). Digest·LLM Director는 이번 범위 밖. 화면의 모든 값은 TraceEvent에서만 나온다.

**Tech Stack:** 기존 Vite + React 19 + TypeScript 프로젝트에 추가: Pyodide 0.26 (CDN, module worker), vitest (순수 로직 테스트), GSAP(기존), Monaco(기존). PixiJS는 보류 자산(수정하지 않음).

## Global Constraints

- 화면에 표시되는 값·순서는 전부 TraceEvent에서만 조회한다 (기획안 §1 "값의 신뢰성")
- 지원 범위: self-contained · single-file · synchronous Python (기획안 §2 매트릭스). D 유형은 preflight에서 차단/안내
- 렌더러는 SVG only. PixiStage.tsx·기존 tracing.ts는 삭제하지 않되 신규 실행 경로에서 사용 금지
- 실행 상한: maxEvents 5000, 실행 타임아웃 10초 (스파이크 전 임시값 — 코드 상수로 한 곳에 정의)
- UI 문구는 한국어, 기존 App.css의 다크 테마·색 체계 계승
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 테스트: 순수 TS 모듈은 vitest, Python tracer는 로컬 CPython으로 동일 파일 실행 검증, UI는 dev 서버 수동 검증

## File Structure

```
src/
  trace/
    types.ts              TraceEvent·Value·ObjectSnap·TraceResult 타입 (파이프라인 공용 계약)
    snapshots.ts          TraceEvent[] → seq별 Snapshot 재구성 (스택·객체·stdout 인덱스)
    preflight.ts          범위 밖 코드(D 매트릭스) 감지
    py/tracer.py          Python 트레이서 (settrace + bounded serializer) — Pyodide와 로컬 CPython 겸용
    tracerWorker.ts       Web Worker: Pyodide 로드·실행·chunk 전송
    tracerClient.ts       메인 스레드 API: runTrace(code) → TraceResult
  screenplay/
    types.ts              Screenplay·Chapter·Scene 타입
    ruleDirector.ts       규칙 기반 대본 생성기
  player/
    expand.ts             Screenplay → PlaybackStep[] (semantic timeline) + narration 치환
  components/
    Stage.tsx             SVG 스테이지 (primitive별 메인 뷰 라우팅)
    views/SequenceView.tsx    리스트 시퀀스 뷰 (GSAP 이동 애니메이션)
    views/ObjectGraphView.tsx 변수→객체 참조 그래프 (aliasing 표현)
    views/CallStackView.tsx   호출 스택 카드
    views/VariablesView.tsx   변수 패널 (Generic State View 겸용)
    PlayerBar.tsx         재생/일시정지/스크럽/배속/챕터 진행바
    Inspector.tsx         일시정지 시 변수·객체 표
  fixtures/
    aliasing.trace.json   Slice 0용 수작업(스크립트 생성) 트레이스
    loop.trace.json
  samples.ts              예제 코드 3종 (aliasing 데모 포함)
scripts/
  gen_fixtures.py         tracer.py를 로컬 CPython으로 돌려 fixture 생성
src/trace/py/tracer_test.py  tracer.py 자체 검증 (로컬 CPython)
```

---

### Task 1: 프로젝트 기반 (git, vitest)

**Files:**
- Create: `.git` (git init), `package.json` 수정 (vitest)

**Interfaces:**
- Produces: `npm test` = `vitest run`. 이후 모든 태스크가 사용

- [ ] **Step 1: git 초기화 및 베이스라인 커밋**

```bash
git init
git add -A
git commit -m "chore: baseline before Algo-Scope MVP build

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 2: vitest 설치·스크립트 추가**

```bash
npm install -D vitest
```

package.json scripts에 추가: `"test": "vitest run"`

- [ ] **Step 3: 동작 확인**

Run: `npx vitest run` → Expected: "No test files found" (에러 아님)

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: add vitest

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Trace 타입 + 스냅샷 재구성

**Files:**
- Create: `src/trace/types.ts`, `src/trace/snapshots.ts`
- Test: `src/trace/snapshots.test.ts`

**Interfaces:**
- Produces (전 파이프라인 공용 계약):

```ts
// src/trace/types.ts — 전체 내용
export type Value =
  | { k: 'prim'; v: string; t: string }   // repr 문자열, 타입명
  | { k: 'ref'; id: number }              // objectId 참조

export type ObjectSnap = {
  id: number
  type: string                            // 'list' | 'dict' | 'tuple' | 'set' | 클래스명
  items?: Value[]                         // list/tuple/set
  entries?: [string, Value][]             // dict 또는 클래스 __dict__
  truncated?: boolean
  unsupported?: boolean
}

export type LocalsDelta = { name: string; op: 'set' | 'delete'; value?: Value }
export type ObjectsDelta = { op: 'set' | 'delete'; obj?: ObjectSnap; id?: number }

export type TraceEvent = {
  seq: number
  kind: 'line' | 'call' | 'return' | 'exception'
  frameId: number
  parentFrameId: number | null
  func: string
  causedByLine: number | null             // 직전에 실행된 줄 (귀속 규칙)
  observedAtLine: number
  localsDelta: LocalsDelta[]
  objectsDelta: ObjectsDelta[]
  stdout: string                          // 이번 이벤트에서 새로 나온 출력
  error?: string
}

export type TraceResult = {
  events: TraceEvent[]
  clipped: boolean
  error?: string
}

export const MAX_EVENTS = 5000
export const EXEC_TIMEOUT_MS = 10000
```

```ts
// src/trace/snapshots.ts — 시그니처
export type FrameState = {
  frameId: number; func: string; parentFrameId: number | null
  locals: Map<string, Value>
}
export type Snapshot = {
  seq: number
  line: number                 // causedByLine ?? observedAtLine — 하이라이트용
  stack: FrameState[]          // [0]=최상위(<module>), 마지막=현재 프레임
  objects: Map<number, ObjectSnap>
  stdout: string               // 누적 출력
}
export function buildSnapshots(events: TraceEvent[]): Snapshot[]
// aliasing 헬퍼: 현재 스냅샷에서 같은 objectId를 가리키는 변수 그룹
export function aliasGroups(s: Snapshot): { id: number; names: string[] }[]
```

- [ ] **Step 1: 실패하는 테스트 작성** (`src/trace/snapshots.test.ts` 전체)

```ts
import { describe, it, expect } from 'vitest'
import type { TraceEvent } from './types'
import { buildSnapshots, aliasGroups } from './snapshots'

const ev = (p: Partial<TraceEvent>): TraceEvent => ({
  seq: 0, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
  causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...p,
})

describe('buildSnapshots', () => {
  const events: TraceEvent[] = [
    ev({ seq: 0, observedAtLine: 1 }),
    ev({ seq: 1, causedByLine: 1, observedAtLine: 2,
      localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 7 } }],
      objectsDelta: [{ op: 'set', obj: { id: 7, type: 'list', items: [{ k: 'prim', v: "'kim'", t: 'str' }] } }] }),
    ev({ seq: 2, causedByLine: 2, observedAtLine: 3,
      localsDelta: [{ name: 'b', op: 'set', value: { k: 'ref', id: 7 } }] }),
    ev({ seq: 3, kind: 'call', frameId: 1, parentFrameId: 0, func: 'f', observedAtLine: 5 }),
    ev({ seq: 4, frameId: 1, func: 'f', observedAtLine: 6,
      localsDelta: [{ name: 'x', op: 'set', value: { k: 'prim', v: '1', t: 'int' } }] }),
    ev({ seq: 5, kind: 'return', frameId: 1, parentFrameId: 0, func: 'f', observedAtLine: 6 }),
    ev({ seq: 6, causedByLine: 3, observedAtLine: 4, stdout: 'hi\n',
      localsDelta: [{ name: 'b', op: 'delete' }] }),
  ]
  const snaps = buildSnapshots(events)

  it('스택이 call/return을 따라간다', () => {
    expect(snaps[3].stack.map(f => f.func)).toEqual(['<module>', 'f'])
    expect(snaps[5].stack.map(f => f.func)).toEqual(['<module>'])   // return 후 pop
  })
  it('locals가 프레임별로 누적된다', () => {
    expect(snaps[2].stack[0].locals.get('a')).toEqual({ k: 'ref', id: 7 })
    expect(snaps[4].stack[1].locals.get('x')).toEqual({ k: 'prim', v: '1', t: 'int' })
  })
  it('delete가 적용된다', () => {
    expect(snaps[6].stack[0].locals.has('b')).toBe(false)
  })
  it('stdout이 누적된다', () => {
    expect(snaps[6].stdout).toBe('hi\n')
  })
  it('aliasing을 감지한다', () => {
    expect(aliasGroups(snaps[2])).toEqual([{ id: 7, names: ['a', 'b'] }])
  })
  it('line은 causedByLine 우선', () => {
    expect(snaps[1].line).toBe(1)
    expect(snaps[0].line).toBe(1)   // causedByLine null → observedAtLine
  })
})
```

- [ ] **Step 2: 실패 확인** — Run: `npx vitest run src/trace/snapshots.test.ts` → Expected: FAIL (모듈 없음)

- [ ] **Step 3: 구현** (`src/trace/types.ts` 위 계약 그대로 + `src/trace/snapshots.ts` 전체)

```ts
import type { TraceEvent, Value, ObjectSnap } from './types'

export type FrameState = {
  frameId: number; func: string; parentFrameId: number | null
  locals: Map<string, Value>
}
export type Snapshot = {
  seq: number; line: number; stack: FrameState[]
  objects: Map<number, ObjectSnap>; stdout: string
}

export function buildSnapshots(events: TraceEvent[]): Snapshot[] {
  const snaps: Snapshot[] = []
  let stack: FrameState[] = []
  let objects = new Map<number, ObjectSnap>()
  let stdout = ''

  const cloneStack = () => stack.map(f => ({ ...f, locals: new Map(f.locals) }))

  for (const e of events) {
    if (e.kind === 'call') {
      stack.push({ frameId: e.frameId, func: e.func, parentFrameId: e.parentFrameId, locals: new Map() })
    }
    let frame = stack.find(f => f.frameId === e.frameId)
    if (!frame) {   // 모듈 프레임은 첫 이벤트에서 암묵 생성
      frame = { frameId: e.frameId, func: e.func, parentFrameId: e.parentFrameId, locals: new Map() }
      stack.push(frame)
    }
    for (const d of e.localsDelta) {
      if (d.op === 'set' && d.value) frame.locals.set(d.name, d.value)
      else frame.locals.delete(d.name)
    }
    if (e.objectsDelta.length) {
      objects = new Map(objects)
      for (const d of e.objectsDelta) {
        if (d.op === 'set' && d.obj) objects.set(d.obj.id, d.obj)
        else if (d.id !== undefined) objects.delete(d.id)
      }
    }
    stdout += e.stdout
    if (e.kind === 'return') stack = stack.filter(f => f.frameId !== e.frameId)
    snaps.push({
      seq: e.seq, line: e.causedByLine ?? e.observedAtLine,
      stack: cloneStack(), objects, stdout,
    })
  }
  return snaps
}

export function aliasGroups(s: Snapshot): { id: number; names: string[] }[] {
  const byId = new Map<number, string[]>()
  for (const f of s.stack) {
    for (const [name, v] of f.locals) {
      if (v.k === 'ref') byId.set(v.id, [...(byId.get(v.id) ?? []), name])
    }
  }
  return [...byId.entries()].filter(([, names]) => names.length > 1)
    .map(([id, names]) => ({ id, names }))
}
```

- [ ] **Step 4: 통과 확인** — Run: `npx vitest run src/trace/snapshots.test.ts` → Expected: PASS (6 tests)

- [ ] **Step 5: Commit** — `git add src/trace && git commit -m "feat: trace types and snapshot reconstruction ..."`

---

### Task 3: Preflight (범위 밖 코드 감지)

**Files:**
- Create: `src/trace/preflight.ts`
- Test: `src/trace/preflight.test.ts`

**Interfaces:**
- Produces: `preflight(code: string): PreflightIssue[]`, `type PreflightIssue = { level: 'block' | 'warn'; code: string; message: string }`

- [ ] **Step 1: 실패하는 테스트 작성** (`src/trace/preflight.test.ts` 전체)

```ts
import { describe, it, expect } from 'vitest'
import { preflight } from './preflight'

const codes = (issues: ReturnType<typeof preflight>) => issues.map(i => i.code)

describe('preflight — D 매트릭스', () => {
  it('input() 차단', () => expect(codes(preflight('name = input("이름: ")'))).toContain('input'))
  it('async/yield/threading 차단', () => {
    expect(codes(preflight('async def f():\n    pass'))).toContain('unsupported-model')
    expect(codes(preflight('def g():\n    yield 1'))).toContain('unsupported-model')
    expect(codes(preflight('import threading'))).toContain('unsupported-model')
  })
  it('네트워크·파일·미지원 라이브러리 차단', () => {
    expect(codes(preflight('import requests'))).toContain('external-dep')
    expect(codes(preflight('f = open("a.txt")'))).toContain('external-dep')
    expect(codes(preflight('from django.db import models'))).toContain('external-dep')
  })
  it('조각 코드(self, 클래스 없음) 경고', () =>
    expect(codes(preflight('def update(self, x):\n    self.repo.find(x)'))).toContain('fragment'))
  it('정의만 있고 호출 없음 경고', () =>
    expect(codes(preflight('def f(x):\n    return x + 1'))).toContain('no-invocation'))
  it('정상 코드는 통과', () => {
    expect(preflight('a = [1,2]\nb = a\nb.append(3)\nprint(a)')).toEqual([])
    expect(codes(preflight('class P:\n    def __init__(self):\n        self.x = 1\np = P()'))).not.toContain('fragment')
  })
})
```

- [ ] **Step 2: 실패 확인** — `npx vitest run src/trace/preflight.test.ts` → FAIL

- [ ] **Step 3: 구현** (`src/trace/preflight.ts` 전체)

```ts
export type PreflightIssue = { level: 'block' | 'warn'; code: string; message: string }

const BLOCKED_MODULES = /^\s*(?:import|from)\s+(requests|urllib|socket|http|django|flask|numpy|pandas|sqlite3|psycopg2)\b/m

export function preflight(source: string): PreflightIssue[] {
  const issues: PreflightIssue[] = []
  const add = (level: 'block' | 'warn', code: string, message: string) =>
    issues.push({ level, code, message })

  if (/\binput\s*\(/.test(source))
    add('block', 'input', '입력 대기 코드(input)는 아직 지원하지 않아요.')
  if (/\basync\s+def\b|\bawait\b|^\s*(?:import|from)\s+threading\b|\byield\b/m.test(source))
    add('block', 'unsupported-model', '이 실행 모델(async/generator/thread)은 아직 지원하지 않아요.')
  if (BLOCKED_MODULES.test(source) || /\bopen\s*\(/.test(source))
    add('block', 'external-dep', '브라우저 실행 환경에서는 네트워크·파일·외부 라이브러리를 사용할 수 없어요. 표준 문법 중심 코드를 넣어주세요.')
  if (/\bself\b/.test(source) && !/^\s*class\s/m.test(source))
    add('warn', 'fragment', '클래스 없이 self를 쓰는 조각 코드 같아요. 독립 실행 가능한 형태로 잘라서 넣어주세요.')

  // 정의만 있고 호출 없음: 들여쓰기 0의 실행문이 def/import/주석뿐인가
  const topLines = source.split(/\r?\n/).filter(l => l.trim() && !/^\s/.test(l))
  const onlyDefs = topLines.length > 0 &&
    topLines.every(l => /^(def |class |import |from |#|@)/.test(l))
  if (onlyDefs)
    add('warn', 'no-invocation', '실행되는 부분이 없어요 — 호출 예시를 한 줄 추가해 주세요. (예: print(f(...)))')

  return issues
}
```

- [ ] **Step 4: 통과 확인** — `npx vitest run src/trace/preflight.test.ts` → PASS
- [ ] **Step 5: Commit**

---

### Task 4: Python Tracer + fixture 생성

**Files:**
- Create: `src/trace/py/tracer.py`, `src/trace/py/tracer_test.py`, `scripts/gen_fixtures.py`
- Create(생성물): `src/fixtures/aliasing.trace.json`, `src/fixtures/loop.trace.json`

**Interfaces:**
- Produces: Python 전역 함수 `run_traced(code_str, emit, max_events=5000)` — emit(json_str)을 chunk마다 호출. json은 TraceEvent 배열(Task 2 계약과 동일 키). 마지막에 `emit('{"done": true, "clipped": ..., "error": ...}')`
- 로컬 CPython과 Pyodide에서 동일 파일 사용 (Task 7이 `?raw` import)

- [ ] **Step 1: 실패하는 테스트 작성** (`src/trace/py/tracer_test.py` 전체)

```python
# -*- coding: utf-8 -*-
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
exec(open(os.path.join(os.path.dirname(__file__), 'tracer.py'), encoding='utf-8').read())

def collect(code):
    chunks = []
    run_traced(code, lambda s: chunks.append(json.loads(s)))
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

# 3) causedByLine 귀속: append(3행)의 효과는 4행 도착 이벤트에서 causedByLine=3
mut_ev = next(e for e in events if any(
    d['op'] == 'set' and d['obj']['id'] == refs['a'] and len(d['obj'].get('items', [])) == 3
    for d in e['objectsDelta']))
assert mut_ev['causedByLine'] == 3, f"귀속 실패: {mut_ev['causedByLine']}"

# 4) 함수 호출: frameId 구분과 call/return
events2, _ = collect("def f(x):\n    return x + 1\nprint(f(1))\n")
kinds = [e['kind'] for e in events2]
assert 'call' in kinds and 'return' in kinds
fids = {e['frameId'] for e in events2 if e['func'] == 'f'}
assert fids and 0 not in fids, "함수 프레임 id 미구분"
assert any('2' in e['stdout'] for e in events2), "stdout 미포착"

# 5) 예외: exception 이벤트 + error 필드
events3, tail3 = collect("arr = [1]\nprint(arr[5])\n")
assert any(e['kind'] == 'exception' for e in events3)
assert tail3.get('error'), "예외 요약 누락"

# 6) 상한: max_events 초과 시 clipped
_, tail4 = collect("i = 0\nwhile True:\n    i += 1\n")   # run_traced 내부 상한이 자름
assert tail4['clipped'] is True

print("tracer_test: ALL PASS")
```

- [ ] **Step 2: 실패 확인** — Run: `python src/trace/py/tracer_test.py` → Expected: FileNotFoundError (tracer.py 없음)

- [ ] **Step 3: 구현** (`src/trace/py/tracer.py` 전체)

```python
# -*- coding: utf-8 -*-
# Algo-Scope Tracer — Pyodide와 로컬 CPython 겸용. sys.settrace 기반.
# 계약: run_traced(code, emit, max_events) → emit(TraceEvent[] JSON) 반복, 마지막 emit({"done":...})
import sys, json, io, contextlib

SAFE_TYPES = (int, float, bool, str, type(None))
MAX_ITEMS = 20        # 컬렉션 원소 상한
MAX_STR = 80          # 문자열 repr 상한
MAX_DEPTH = 2         # 중첩 직렬화 깊이
CHUNK_SIZE = 200

def _prim(v):
    r = repr(v)
    if len(r) > MAX_STR: r = r[:MAX_STR] + '…'
    return {'k': 'prim', 'v': r, 't': type(v).__name__}

def _serialize(v, objects, depth=0):
    """값 → Value. 컬렉션·객체는 objects에 ObjectSnap 등록 후 ref 반환. 부작용 없는 경로만."""
    if isinstance(v, SAFE_TYPES): return _prim(v)
    oid = id(v)
    ref = {'k': 'ref', 'id': oid}
    if depth > MAX_DEPTH:
        objects[oid] = {'id': oid, 'type': type(v).__name__, 'truncated': True}
        return ref
    if isinstance(v, (list, tuple, set)):
        items = list(v)[:MAX_ITEMS]
        objects[oid] = {'id': oid, 'type': type(v).__name__,
                        'items': [_serialize(x, objects, depth + 1) for x in items],
                        'truncated': len(v) > MAX_ITEMS}
    elif isinstance(v, dict):
        entries = list(v.items())[:MAX_ITEMS]
        objects[oid] = {'id': oid, 'type': 'dict',
                        'entries': [[str(k)[:MAX_STR], _serialize(x, objects, depth + 1)] for k, x in entries],
                        'truncated': len(v) > MAX_ITEMS}
    else:
        d = getattr(v, '__dict__', None)          # 부작용 적은 경로만 관찰
        if isinstance(d, dict):
            entries = list(d.items())[:MAX_ITEMS]
            objects[oid] = {'id': oid, 'type': type(v).__name__,
                            'entries': [[str(k), _serialize(x, objects, depth + 1)] for k, x in entries]}
        else:
            objects[oid] = {'id': oid, 'type': type(v).__name__, 'unsupported': True}
    return ref

class _Tracer:
    def __init__(self, emit, max_events):
        self.emit = emit; self.max_events = max_events
        self.events = []; self.buffer = []
        self.seq = 0; self.clipped = False
        self.frame_ids = {}; self.next_fid = 0
        self.prev_locals = {}     # fid → {name: json문자열(Value)}
        self.prev_objects = {}    # oid → json문자열(ObjectSnap)
        self.last_line = {}       # fid → 직전 줄
        self.stdout = io.StringIO(); self.stdout_sent = 0

    def _fid(self, frame):
        key = id(frame)
        if key not in self.frame_ids:
            self.frame_ids[key] = self.next_fid; self.next_fid += 1
        return self.frame_ids[key]

    def _flush(self, force=False):
        if len(self.buffer) >= CHUNK_SIZE or (force and self.buffer):
            self.emit(json.dumps(self.buffer)); self.buffer = []

    def _new_stdout(self):
        s = self.stdout.getvalue()
        out = s[self.stdout_sent:]; self.stdout_sent = len(s)
        return out

    def _record(self, frame, kind, err=None):
        if self.clipped: return
        if self.seq >= self.max_events:
            self.clipped = True; raise _Stop()
        fid = self._fid(frame)
        parent = self.frame_ids.get(id(frame.f_back)) if frame.f_back else None
        objects = {}
        cur = {}
        for name, val in frame.f_locals.items():
            if name.startswith('__'): continue
            cur[name] = json.dumps(_serialize(val, objects))
        prev = self.prev_locals.get(fid, {})
        delta = []
        for name, vjson in cur.items():
            if prev.get(name) != vjson:
                delta.append({'name': name, 'op': 'set', 'value': json.loads(vjson)})
        for name in prev:
            if name not in cur:
                delta.append({'name': name, 'op': 'delete'})
        self.prev_locals[fid] = cur
        obj_delta = []
        for oid, snap in objects.items():
            sjson = json.dumps(snap, sort_keys=True)
            if self.prev_objects.get(oid) != sjson:
                self.prev_objects[oid] = sjson
                obj_delta.append({'op': 'set', 'obj': snap})
        ev = {'seq': self.seq, 'kind': kind, 'frameId': fid, 'parentFrameId': parent,
              'func': frame.f_code.co_name if frame.f_code.co_name != '<module>' else '<module>',
              'causedByLine': self.last_line.get(fid), 'observedAtLine': frame.f_lineno,
              'localsDelta': delta, 'objectsDelta': obj_delta, 'stdout': self._new_stdout()}
        if err: ev['error'] = err
        self.last_line[fid] = frame.f_lineno
        self.seq += 1
        self.buffer.append(ev); self._flush()

    def __call__(self, frame, event, arg):
        if frame.f_code.co_filename != '<user>': return None
        if event == 'line': self._record(frame, 'line')
        elif event == 'call': self.last_line.pop(self._fid(frame), None); self._record(frame, 'call')
        elif event == 'return': self._record(frame, 'return')
        elif event == 'exception':
            self._record(frame, 'exception', err=f"{arg[0].__name__}: {arg[1]}")
        return self

class _Stop(Exception): pass

def run_traced(code, emit, max_events=5000):
    tracer = _Tracer(emit, max_events)
    error = None
    compiled = compile(code, '<user>', 'exec')
    with contextlib.redirect_stdout(tracer.stdout):
        sys.settrace(tracer)
        try:
            exec(compiled, {})
        except _Stop:
            pass
        except BaseException as e:
            error = f"{type(e).__name__}: {e}"
        finally:
            sys.settrace(None)
    tracer._flush(force=True)
    emit(json.dumps({'done': True, 'clipped': tracer.clipped, 'error': error}))
```

- [ ] **Step 4: 통과 확인** — Run: `PYTHONIOENCODING=utf-8 python src/trace/py/tracer_test.py` → Expected: `tracer_test: ALL PASS`

- [ ] **Step 5: fixture 생성 스크립트** (`scripts/gen_fixtures.py` 전체)

```python
# -*- coding: utf-8 -*-
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'trace', 'py'))
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
```

Run: `PYTHONIOENCODING=utf-8 python scripts/gen_fixtures.py` → Expected: 두 파일 생성, 각 이벤트 수 출력

- [ ] **Step 6: Commit** — tracer.py, tracer_test.py, gen_fixtures.py, fixtures 2개

---

### Task 5: 규칙 기반 대본 생성기 (ruleDirector)

**Files:**
- Create: `src/screenplay/types.ts`, `src/screenplay/ruleDirector.ts`
- Test: `src/screenplay/ruleDirector.test.ts`

**Interfaces:**
- Consumes: `TraceEvent`, `buildSnapshots`, `aliasGroups` (Task 2)
- Produces:

```ts
// src/screenplay/types.ts — 전체 내용
export type PrimitiveKind = 'variables' | 'callStack' | 'sequence' | 'objectGraph' | 'generic'
export type Pacing = 'slow' | 'normal' | 'fast'
export type Scene = {
  seqStart: number; seqEnd: number
  primitive: PrimitiveKind
  focus: string[]                 // 변수명 목록 (빈 배열 = 전체)
  pacing: Pacing
  repeat?: number                 // fast(빨리감기) 장면의 반복 횟수 표시
  narration: { template: string; bindings: Record<string, { seq: number; name: string }> }
}
export type Chapter = { title: string; scenes: Scene[] }
export type Screenplay = { chapters: Chapter[] }
```

- `buildScreenplay(events: TraceEvent[]): Screenplay`

**규칙 명세** (구현·테스트의 기준):
1. 챕터 분할: `<module>` 프레임에서 첫 `call` 이전 구간 = "변수 준비" / 각 최상위 call~return 구간 = `"{함수명} 실행"` / 이후 구간 = "마무리" / exception 이벤트가 있으면 해당 구간 챕터 제목 = "예외 발생". call이 없으면 챕터 1개 "실행".
2. 장면·프리미티브 (이벤트 1개 = 장면 1개, 단 루프 접기 제외):
   - 그 시점 스냅샷에 aliasGroups가 비어있지 않고 이번 이벤트가 그 객체를 변경(objectsDelta에 해당 id) 또는 생성했다면 → `objectGraph`, pacing `slow`
   - objectsDelta에 list/tuple/set 변경이 있으면 → `sequence`
   - kind가 call/return이면 → `callStack`
   - 그 외 → `variables`
3. 루프 접기: 같은 frameId에서 같은 observedAtLine이 3번째 이상 등장하는 이벤트부터는 연속 구간을 하나의 장면으로 합침 — primitive는 구간 내 규칙 적용 결과 중 다수결, pacing `fast`, repeat = 합쳐진 이벤트 수, narration "같은 반복이 계속됩니다 (×{n}회)".
4. narration (관찰형만, 값은 바인딩으로):
   - set: `"{name}이(가) {value}로 설정됩니다"` → bindings `{ value: { seq, name } }` (name은 변수명 그대로 template에 리터럴 삽입)
   - aliasing 생성(objectGraph + localsDelta의 ref가 기존 그룹과 병합): `"{b}는 새 객체가 아니라 {a}와 같은 객체를 가리킵니다"` (변수명 리터럴)
   - mutation(sequence): `"{name}의 내용이 변경됩니다"`
   - call: `"{func} 함수가 호출됩니다"` / return: `"{func} 함수가 값을 돌려주고 종료됩니다"`
   - exception: `"여기서 {error}가 발생합니다"` (error는 이벤트의 error 리터럴)
   - localsDelta 여러 개면 첫 항목 기준.

- [ ] **Step 1: 실패하는 테스트 작성** (`src/screenplay/ruleDirector.test.ts` 전체 — fixture 사용)

```ts
import { describe, it, expect } from 'vitest'
import aliasingFixture from '../fixtures/aliasing.trace.json'
import loopFixture from '../fixtures/loop.trace.json'
import { buildScreenplay } from './ruleDirector'
import type { TraceEvent } from '../trace/types'

const aliasing = (aliasingFixture as { events: TraceEvent[] }).events
const loop = (loopFixture as { events: TraceEvent[] }).events

describe('buildScreenplay', () => {
  it('모든 장면의 seq 구간이 단조 증가하고 트레이스 안에 있다', () => {
    const sp = buildScreenplay(aliasing)
    let last = -1
    for (const ch of sp.chapters) for (const sc of ch.scenes) {
      expect(sc.seqStart).toBeGreaterThan(last)
      expect(sc.seqEnd).toBeLessThan(aliasing.length)
      last = sc.seqEnd
    }
  })
  it('aliasing 트레이스에서 objectGraph 장면이 나온다', () => {
    const sp = buildScreenplay(aliasing)
    const prims = sp.chapters.flatMap(c => c.scenes).map(s => s.primitive)
    expect(prims).toContain('objectGraph')
  })
  it('루프 트레이스에서 fast(접기) 장면이 나온다', () => {
    const sp = buildScreenplay(loop)
    const fast = sp.chapters.flatMap(c => c.scenes).find(s => s.pacing === 'fast')
    expect(fast).toBeDefined()
    expect(fast!.repeat).toBeGreaterThan(1)
  })
  it('call 없는 코드는 챕터 1개', () => {
    const sp = buildScreenplay(loop.filter(e => e.kind !== 'call' && e.kind !== 'return'))
    expect(sp.chapters.length).toBe(1)
  })
  it('narration 템플릿은 값 문자열을 직접 포함하지 않는다 (바인딩 강제)', () => {
    const sp = buildScreenplay(aliasing)
    for (const sc of sp.chapters.flatMap(c => c.scenes)) {
      if (sc.narration.template.includes('{value}'))
        expect(sc.narration.bindings.value).toBeDefined()
    }
  })
})
```

- [ ] **Step 2: 실패 확인** — `npx vitest run src/screenplay/ruleDirector.test.ts` → FAIL

- [ ] **Step 3: 구현** (`src/screenplay/ruleDirector.ts` — 규칙 명세 1~4를 그대로 코드화. 아래 뼈대 완성형)

```ts
import type { TraceEvent } from '../trace/types'
import { buildSnapshots, aliasGroups } from '../trace/snapshots'
import type { Screenplay, Chapter, Scene, PrimitiveKind } from './types'

export function buildScreenplay(events: TraceEvent[]): Screenplay {
  if (events.length === 0) return { chapters: [] }
  const snaps = buildSnapshots(events)
  const lineCount = new Map<string, number>()   // `${frameId}:${line}` 등장 횟수

  const sceneFor = (e: TraceEvent, i: number): Scene => {
    const aliases = aliasGroups(snaps[i])
    const touchedAlias = aliases.find(g =>
      e.objectsDelta.some(d => d.obj?.id === g.id) ||
      e.localsDelta.some(d => d.value?.k === 'ref' && d.value.id === g.id))
    let primitive: PrimitiveKind = 'variables'
    let template = ''
    const bindings: Scene['narration']['bindings'] = {}
    const firstSet = e.localsDelta.find(d => d.op === 'set')

    if (e.kind === 'call') { primitive = 'callStack'; template = `${e.func} 함수가 호출됩니다` }
    else if (e.kind === 'return') { primitive = 'callStack'; template = `${e.func} 함수가 값을 돌려주고 종료됩니다` }
    else if (e.kind === 'exception') { primitive = 'variables'; template = `여기서 ${e.error ?? '예외'}가 발생합니다` }
    else if (touchedAlias) {
      primitive = 'objectGraph'
      const [a, b] = touchedAlias.names
      template = e.localsDelta.some(d => d.value?.k === 'ref')
        ? `${b}는 새 객체가 아니라 ${a}와 같은 객체를 가리킵니다`
        : `${touchedAlias.names.join('/')}가 함께 변경됩니다 — 같은 객체이기 때문입니다`
    }
    else if (e.objectsDelta.some(d => ['list', 'tuple', 'set'].includes(d.obj?.type ?? ''))) {
      primitive = 'sequence'
      const name = firstSet?.name ?? focusNames(e)[0] ?? '컬렉션'
      template = `${name}의 내용이 변경됩니다`
    }
    else if (firstSet) {
      template = `${firstSet.name}이(가) {value}로 설정됩니다`
      bindings.value = { seq: e.seq, name: firstSet.name }
    }
    else template = `${e.observedAtLine}행으로 이동합니다`

    return {
      seqStart: e.seq, seqEnd: e.seq, primitive,
      focus: focusNames(e), pacing: touchedAlias ? 'slow' : 'normal',
      narration: { template, bindings },
    }
  }

  const focusNames = (e: TraceEvent) => e.localsDelta.map(d => d.name)

  // 장면 생성 + 루프 접기
  const scenes: Scene[] = []
  let folding: Scene | null = null
  events.forEach((e, i) => {
    const key = `${e.frameId}:${e.observedAtLine}`
    const n = (lineCount.get(key) ?? 0) + 1
    lineCount.set(key, n)
    if (n >= 3 && e.kind === 'line') {
      if (folding) { folding.seqEnd = e.seq; folding.repeat = (folding.repeat ?? 1) + 1 }
      else folding = { seqStart: e.seq, seqEnd: e.seq, primitive: 'variables', focus: [],
        pacing: 'fast', repeat: 1,
        narration: { template: '같은 반복이 계속됩니다', bindings: {} } }
      return
    }
    if (folding) { scenes.push(folding); folding = null }
    scenes.push(sceneFor(e, i))
  })
  if (folding) scenes.push(folding)

  // 챕터 분할 (규칙 1)
  const chapters: Chapter[] = []
  let current: Chapter = { title: '변수 준비', scenes: [] }
  let sawCall = false
  for (const sc of scenes) {
    const ev = events[sc.seqStart]
    if (ev.kind === 'call' && ev.parentFrameId === 0) {
      if (current.scenes.length) chapters.push(current)
      current = { title: `${ev.func} 실행`, scenes: [sc] }
      sawCall = true
      continue
    }
    if (ev.kind === 'exception' && current.title !== '예외 발생') {
      if (current.scenes.length) chapters.push(current)
      current = { title: '예외 발생', scenes: [sc] }
      continue
    }
    if (sawCall && ev.frameId === 0 && ev.kind === 'line' && current.title.endsWith('실행')) {
      chapters.push(current)
      current = { title: '마무리', scenes: [sc] }
      sawCall = false
      continue
    }
    current.scenes.push(sc)
  }
  if (current.scenes.length) chapters.push(current)
  if (chapters.length === 1) chapters[0].title = '실행'
  return { chapters }
}
```

- [ ] **Step 4: 통과 확인** — `npx vitest run src/screenplay/ruleDirector.test.ts` → PASS
- [ ] **Step 5: Commit**

---

### Task 6: 재생 스텝 전개 + narration 치환 (expand)

**Files:**
- Create: `src/player/expand.ts`
- Test: `src/player/expand.test.ts`

**Interfaces:**
- Consumes: `Screenplay`(Task 5), `Snapshot[]`(Task 2)
- Produces:

```ts
export type PlaybackStep = {
  seq: number; chapterIndex: number
  primitive: PrimitiveKind; focus: string[]
  narration: string          // 치환 완료 문장
  durationMs: number
}
export function expandScreenplay(sp: Screenplay, snaps: Snapshot[]): PlaybackStep[]
export const PACING_MS = { slow: 1800, normal: 1000, fast: 180 } as const
```

치환 규칙: bindings의 `{ seq, name }`으로 `snaps[seq]`의 스택에서 변수 값을 찾아 (`ref`면 objects에서 요약 문자열: list → `[a, b, c]` 형태, 그 외 타입명) `{key}` 자리에 삽입. fast 장면은 seqStart와 seqEnd 두 스텝만 생성(중간 생략)하고 narration에 `(×N회)`를 덧붙인다.

- [ ] **Step 1: 실패하는 테스트 작성** (`src/player/expand.test.ts` 전체)

```ts
import { describe, it, expect } from 'vitest'
import loopFixture from '../fixtures/loop.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildSnapshots } from '../trace/snapshots'
import { buildScreenplay } from '../screenplay/ruleDirector'
import { expandScreenplay, PACING_MS } from './expand'

const events = (loopFixture as { events: TraceEvent[] }).events
const snaps = buildSnapshots(events)
const steps = expandScreenplay(buildScreenplay(events), snaps)

describe('expandScreenplay', () => {
  it('스텝 seq가 단조 증가한다', () => {
    for (let i = 1; i < steps.length; i++) expect(steps[i].seq).toBeGreaterThan(steps[i - 1].seq)
  })
  it('narration에 미치환 {키}가 남지 않는다', () => {
    for (const s of steps) expect(s.narration).not.toMatch(/\{[a-z]+\}/i)
  })
  it('값이 치환된다 (total 설정 스텝에 실제 숫자)', () => {
    const set = steps.find(s => s.narration.includes('total이(가)'))
    expect(set).toBeDefined()
    expect(set!.narration).toMatch(/[0-9]/)
  })
  it('fast 장면은 2스텝으로 접히고 ×N이 붙는다', () => {
    const fast = steps.filter(s => s.durationMs === PACING_MS.fast)
    expect(fast.length).toBeLessThanOrEqual(4)
    expect(fast.some(s => /×\d+회/.test(s.narration))).toBe(true)
  })
  it('chapterIndex가 챕터 경계를 따라간다', () => {
    expect(new Set(steps.map(s => s.chapterIndex)).size).toBeGreaterThanOrEqual(1)
  })
})
```

- [ ] **Step 2: 실패 확인** — `npx vitest run src/player/expand.test.ts` → FAIL

- [ ] **Step 3: 구현** (`src/player/expand.ts` 전체)

```ts
import type { Screenplay, PrimitiveKind } from '../screenplay/types'
import type { Snapshot } from '../trace/snapshots'
import type { Value, ObjectSnap } from '../trace/types'

export type PlaybackStep = {
  seq: number; chapterIndex: number
  primitive: PrimitiveKind; focus: string[]
  narration: string; durationMs: number
}
export const PACING_MS = { slow: 1800, normal: 1000, fast: 180 } as const

function valueLabel(v: Value | undefined, objects: Map<number, ObjectSnap>): string {
  if (!v) return '?'
  if (v.k === 'prim') return v.v
  const o = objects.get(v.id)
  if (!o) return '객체'
  if (o.items) return `[${o.items.map(x => valueLabel(x, objects)).join(', ')}${o.truncated ? ', …' : ''}]`
  if (o.entries) return `{${o.entries.map(([k, x]) => `${k}: ${valueLabel(x, objects)}`).join(', ')}}`
  return o.type
}

function lookup(snap: Snapshot, name: string): Value | undefined {
  for (let i = snap.stack.length - 1; i >= 0; i--) {
    const v = snap.stack[i].locals.get(name)
    if (v) return v
  }
  return undefined
}

export function expandScreenplay(sp: Screenplay, snaps: Snapshot[]): PlaybackStep[] {
  const steps: PlaybackStep[] = []
  sp.chapters.forEach((ch, chapterIndex) => {
    for (const sc of ch.scenes) {
      let narration = sc.narration.template
      for (const [key, b] of Object.entries(sc.narration.bindings)) {
        const snap = snaps[b.seq]
        narration = narration.replaceAll(`{${key}}`, snap ? valueLabel(lookup(snap, b.name), snap.objects) : '?')
      }
      const durationMs = PACING_MS[sc.pacing]
      if (sc.pacing === 'fast' && sc.seqEnd > sc.seqStart) {
        const label = `${narration} (×${sc.repeat ?? sc.seqEnd - sc.seqStart + 1}회)`
        steps.push({ seq: sc.seqStart, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration: label, durationMs })
        steps.push({ seq: sc.seqEnd, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration: label, durationMs })
      } else {
        steps.push({ seq: sc.seqStart, chapterIndex, primitive: sc.primitive, focus: sc.focus, narration, durationMs })
      }
    }
  })
  return steps
}
```

- [ ] **Step 4: 통과 확인** — `npx vitest run src/player/expand.test.ts` → PASS
- [ ] **Step 5: Commit**

---

### Task 7: Tracer Worker + Client (브라우저 실행)

**Files:**
- Create: `src/trace/tracerWorker.ts`, `src/trace/tracerClient.ts`
- Modify: `src/vite-env.d.ts` (raw import 선언)

**Interfaces:**
- Consumes: `tracer.py`(Task 4, `?raw` import), `TraceEvent`/`TraceResult`/상수(Task 2)
- Produces: `runTrace(code: string, onStage: (s: TraceStage) => void): Promise<TraceResult>`, `type TraceStage = 'python-loading' | 'executing' | 'building'`

- [ ] **Step 1: 구현** (`src/trace/tracerWorker.ts` 전체)

```ts
/// <reference lib="webworker" />
import tracerSource from './py/tracer.py?raw'

const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.mjs'
let pyodidePromise: Promise<any> | null = null

async function getPyodide() {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      const mod = await import(/* @vite-ignore */ PYODIDE_URL)
      const py = await mod.loadPyodide()
      py.runPython(tracerSource)
      return py
    })()
  }
  return pyodidePromise
}

self.onmessage = async (e: MessageEvent<{ code: string; maxEvents: number }>) => {
  try {
    self.postMessage({ type: 'stage', stage: 'python-loading' })
    const py = await getPyodide()
    self.postMessage({ type: 'stage', stage: 'executing' })
    py.globals.set('js_emit', (s: string) => self.postMessage({ type: 'chunk', json: s }))
    py.globals.set('user_code', e.data.code)
    py.globals.set('max_events', e.data.maxEvents)
    py.runPython('run_traced(user_code, js_emit, max_events)')
  } catch (err) {
    self.postMessage({ type: 'fatal', message: String(err) })
  }
}
```

- [ ] **Step 2: 구현** (`src/trace/tracerClient.ts` 전체)

```ts
import type { TraceEvent, TraceResult } from './types'
import { MAX_EVENTS, EXEC_TIMEOUT_MS } from './types'

export type TraceStage = 'python-loading' | 'executing' | 'building'

let worker: Worker | null = null
const makeWorker = () => new Worker(new URL('./tracerWorker.ts', import.meta.url), { type: 'module' })

export function warmUp() { if (!worker) worker = makeWorker() }   // 페이지 진입 시 선로딩

export function runTrace(code: string, onStage: (s: TraceStage) => void): Promise<TraceResult> {
  if (!worker) worker = makeWorker()
  const w = worker
  const events: TraceEvent[] = []
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      w.terminate(); worker = null                     // chunk flush 덕에 수집분은 보존
      finish({ events, clipped: true, error: '실행 시간이 너무 깁니다 (10초 제한)' })
    }, EXEC_TIMEOUT_MS)
    const finish = (r: TraceResult) => { clearTimeout(timeout); w.onmessage = null; resolve(r) }
    w.onmessage = (e: MessageEvent) => {
      const m = e.data
      if (m.type === 'stage') onStage(m.stage)
      else if (m.type === 'chunk') {
        const parsed = JSON.parse(m.json)
        if (Array.isArray(parsed)) events.push(...parsed)
        else { onStage('building'); finish({ events, clipped: parsed.clipped, error: parsed.error ?? undefined }) }
      }
      else if (m.type === 'fatal') finish({ events, clipped: false, error: m.message })
    }
    w.postMessage({ code, maxEvents: MAX_EVENTS })
  })
}
```

`src/vite-env.d.ts`에 추가:

```ts
declare module '*.py?raw' { const src: string; export default src }
```

- [ ] **Step 3: 브라우저 수동 검증** — dev 서버 실행 후 콘솔에서:

```
브라우저 콘솔: const { runTrace } = await import('/src/trace/tracerClient.ts')
await runTrace('a=[1,2]\nb=a\nb.append(3)\nprint(a)', console.log)
```

Expected: `{ events: [...], clipped: false }` — events에 aliasing ref 확인. 첫 실행은 Pyodide 다운로드로 수 초 소요, 두 번째부터 즉시.

- [ ] **Step 4: Commit**

---

### Task 8: SVG 스테이지 (프리미티브 뷰 4종)

**Files:**
- Create: `src/components/Stage.tsx`, `src/components/views/VariablesView.tsx`, `src/components/views/CallStackView.tsx`, `src/components/views/SequenceView.tsx`, `src/components/views/ObjectGraphView.tsx`
- Modify: `src/App.css` (스테이지 스타일 추가)

**Interfaces:**
- Consumes: `Snapshot`(Task 2), `PlaybackStep`(Task 6), `aliasGroups`
- Produces: `<Stage snapshot={Snapshot} step={PlaybackStep} />` — primitive에 따라 메인 뷰 라우팅. 각 뷰는 `{ snapshot: Snapshot; focus: string[] }` props.

**공통 규격:** 각 뷰는 순수 SVG(뷰박스 0 0 720 420). 색: 기본 `#38d7e8`, 활성(focus) `#ff4fd8`, 확정 `#68ff7a`, 흐림 `#556070` (기존 상태색 계승). 텍스트 12~14px. SequenceView는 원소 x좌표 변경 시 `gsap.to`로 0.4s 이동(요소 key = 안정적 인덱스), 나머지 뷰는 CSS opacity 트랜지션.

**뷰별 렌더 명세:**
- `VariablesView`: 현재 프레임(스택 마지막) locals를 2열 카드로 — 이름/값(valueLabel 재사용을 위해 expand.ts의 valueLabel을 export). focus에 든 이름은 활성색. Generic State View 겸용 (모든 타입 커버).
- `CallStackView`: snapshot.stack을 아래→위 카드 스택으로, 각 카드에 함수명 + locals 요약 (이름=값, 3개까지). 최상단 카드 활성색 테두리.
- `SequenceView`: focus 첫 변수(또는 스냅샷에서 첫 list ref 변수)의 리스트를 칸 상자 나열로. 각 칸 위 인덱스, 안에 값. focus면 마지막 변경 칸 활성색.
- `ObjectGraphView`: 왼쪽에 변수 이름표(둥근 사각형), 오른쪽에 객체 상자(리스트면 칸 나열, dict/객체면 key: value 행), 참조 화살표(`<path>` + marker). 같은 객체를 가리키는 변수 2개 이상이면 화살표가 한 상자로 모임 — aliasing 시각화의 핵심. 객체 상자 위 `type · id` 라벨.

- [ ] **Step 1: 구현** — 위 명세대로 5개 파일 작성. Stage.tsx 라우팅:

```tsx
import type { Snapshot } from '../trace/snapshots'
import type { PlaybackStep } from '../player/expand'
import VariablesView from './views/VariablesView'
import CallStackView from './views/CallStackView'
import SequenceView from './views/SequenceView'
import ObjectGraphView from './views/ObjectGraphView'

export default function Stage({ snapshot, step }: { snapshot?: Snapshot; step?: PlaybackStep }) {
  if (!snapshot || !step) return <div className="stage-empty">Run을 누르면 실행 영상이 시작됩니다</div>
  const props = { snapshot, focus: step.focus }
  switch (step.primitive) {
    case 'sequence': return <SequenceView {...props} />
    case 'objectGraph': return <ObjectGraphView {...props} />
    case 'callStack': return <CallStackView {...props} />
    default: return <VariablesView {...props} />
  }
}
```

- [ ] **Step 2: Slice 0 수동 검증** — App에 임시 코드로 fixture 재생: `aliasing.trace.json`을 import → buildSnapshots → buildScreenplay → expandScreenplay → 스텝 배열을 1초 간격 setInterval로 넘기며 Stage 렌더. dev 서버에서 확인:
  - aliasing 장면에서 team_a·team_b 화살표가 한 상자로 모이는가
  - append 장면에서 시퀀스 칸이 늘어나는가
  - 콘솔 에러 0건
- [ ] **Step 3: Commit**

---

### Task 9: 플레이어 UI (재생 컨트롤·챕터바·자막·인스펙터)

**Files:**
- Create: `src/components/PlayerBar.tsx`, `src/components/Inspector.tsx`, `src/player/usePlayback.ts`
- Modify: `src/App.css`

**Interfaces:**
- Consumes: `PlaybackStep[]`(Task 6), `Snapshot[]`(Task 2)
- Produces:

```ts
// src/player/usePlayback.ts — 재생 엔진 훅
export function usePlayback(steps: PlaybackStep[]): {
  index: number; playing: boolean; speed: number
  play(): void; pause(): void; seek(i: number): void; setSpeed(x: number): void
}
```

동작: play 중 `setTimeout(durationMs / speed)` 체인으로 index 전진, 끝에서 자동 pause. seek/pause는 즉시 반영 (semantic timeline: index가 곧 확정 seq — 애니메이션 중간 상태를 인스펙터에 노출하지 않음).

- `PlayerBar`: ▶/⏸(lucide Play/Pause), 진행바(챕터 경계마다 구분선 + 챕터명 툴팁, 클릭·드래그 seek), 배속 0.5/1/1.5/2, 현재 챕터명 표시. 기존 App.css `.playback` 스타일 계승.
- `Inspector`: `playing === false`일 때만 표시 — 현재 snapshot의 전체 프레임 변수 표 + stdout 누적 출력. (일시정지 인스펙터 = 기획안 차별 요소)
- 내레이션 자막 바: Stage 하단 고정, 현재 step.narration 표시, step 변경 시 opacity 페이드.

- [ ] **Step 1: usePlayback 테스트 작성** (`src/player/usePlayback.test.ts` — 타이머 fake)

```ts
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
// @testing-library/react 미설치 시: npm i -D @testing-library/react jsdom, vitest config에 environment: 'jsdom'
import { usePlayback } from './usePlayback'
import type { PlaybackStep } from './expand'

const step = (seq: number): PlaybackStep =>
  ({ seq, chapterIndex: 0, primitive: 'variables', focus: [], narration: '', durationMs: 100 })

describe('usePlayback', () => {
  it('play하면 전진하고 끝에서 멈춘다', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => usePlayback([step(0), step(1), step(2)]))
    act(() => result.current.play())
    act(() => vi.advanceTimersByTime(120))
    expect(result.current.index).toBe(1)
    act(() => vi.advanceTimersByTime(300))
    expect(result.current.index).toBe(2)
    expect(result.current.playing).toBe(false)
    vi.useRealTimers()
  })
  it('seek은 즉시 반영되고 재생을 멈춘다', () => {
    const { result } = renderHook(() => usePlayback([step(0), step(1), step(2)]))
    act(() => result.current.seek(2))
    expect(result.current.index).toBe(2)
    expect(result.current.playing).toBe(false)
  })
})
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과** — 훅 구현 (steps 변경 시 index 0 리셋 포함), 컴포넌트 구현
- [ ] **Step 3: dev 서버 수동 검증** — 재생/일시정지/스크럽/배속, 일시정지 시 인스펙터 표시
- [ ] **Step 4: Commit**

---

### Task 10: App 통합 (Run 플로우 + 로딩 단계 + 구조 정리)

**Files:**
- Create: `src/samples.ts` (예제 3종: aliasing 데모 / 루프 합계 / 예외 데모 — 기존 정렬 프리셋 대체)
- Modify: `src/App.tsx` (전면 개편), `src/App.css`
- 사용 중단(파일은 보존): `src/tracing.ts`, `src/PixiStage.tsx` — import 제거만

**Run 플로우 (기획안 §6 그대로):**

```
Run 클릭
 → preflight(code): block 있으면 실행하지 않고 안내 배너 표시, warn은 배너 + 계속
 → runTrace(code, onStage): 로딩 오버레이에 단계 표시
     python-loading → "Python 환경 준비 중"
     executing      → "코드 실행·기록 중"
     building       → "설명 준비 중"
 → buildSnapshots → buildScreenplay → expandScreenplay
 → usePlayback으로 자동 재생 시작 (result.error 있으면 마지막까지 재생 — 예외도 콘텐츠)
 → clipped면 "실행이 길어 여기까지 시각화했어요" 배너
```

**레이아웃:** 기존 구조 계승 — 좌: Monaco(현재 줄 하이라이트 = `snaps[steps[index].seq].line`, 기존 decoration 로직 재사용) + 예제 버튼 + Run / 우: Stage + 자막 바 + PlayerBar + Inspector. 상단 상태 스트립의 "frontend preview" → "Slice 1 · rule-based" 로 변경. 페이지 마운트 시 `warmUp()` 호출 (콜드 스타트 선로딩).

- [ ] **Step 1: samples.ts 작성** (aliasing 데모는 fixture와 동일 코드 + 주석)
- [ ] **Step 2: App.tsx 개편** — 위 플로우 그대로. 기존 `buildPreviewTrace`·`PixiStage` import 제거
- [ ] **Step 3: 검증** — `npx tsc -b && npx vitest run` 전부 PASS, dev 서버에서 예제 3종 각각 Run
- [ ] **Step 4: Commit**

---

### Task 11: E2E 수동 검증 (지원 매트릭스 스모크)

**Files:**
- Create: `docs/superpowers/plans/2026-08-11-e2e-checklist.md` (결과 기록)

- [ ] **Step 1: 매트릭스별 시나리오 실행** — dev 서버에서 순서대로:

| # | 입력 | 기대 결과 (기획안 §2 매트릭스) |
|---|---|---|
| A1 | aliasing 예제 | objectGraph 장면에서 화살표 2개가 한 상자로 모임, 자막에 "같은 객체" |
| A2 | 루프 예제 | fast 장면 "×N회", total 값이 실제 실행값과 일치 |
| A3 | `arr=[1]` + `arr[5]` | 예외 지점까지 재생, "IndexError 발생" 자막 |
| A4 | 재귀 `f(3)` 팩토리얼 | callStack 카드가 쌓였다 줄어듦 |
| C1 | `while True: i+=1` | 10초 내 종료, clipped 배너, 수집분 재생 |
| D1 | `input()` 포함 | 실행 없이 차단 배너 |
| D2 | `import requests` | 실행 없이 차단 배너 |
| D3 | def만 있는 코드 | "호출 예시 추가" 경고 |

- [ ] **Step 2: 각 항목 통과/실패를 체크리스트 파일에 기록, 실패는 수정 후 재검증**
- [ ] **Step 3: 최종 Commit + 태그** — `git tag slice-1`

---

## Self-Review 결과

- **Spec coverage**: §1 값 신뢰성(모든 뷰가 snapshot에서만 읽음), §2 매트릭스(Task 3·11), §4 계약(Task 2 타입 — 단 Digest·DigestSpan·spanRef는 LLM 없는 Slice 1 범위 밖이라 미구현, ruleDirector는 seq 직접 참조 허용: 결정적 코드이므로 기획안 원칙 위배 아님), §5 프리미티브 5종(코드 하이라이트=Monaco, 나머지 4종=Task 8) + Generic State View(VariablesView 겸용), §6 재생 경험(Task 9·10), §7 에러 처리(예외=콘텐츠, 3중 상한 중 maxEvents·타임아웃 2종 — maxSerializedBytes는 스파이크 후), 착수 순서(Slice 0=Task 8 Step 2, Slice 1=전체)
- **Placeholder scan**: 통과 — 모든 태스크에 실제 코드/명세 포함. Task 8·9 UI는 렌더 명세+검증 기준으로 대체(시각 결과물은 코드보다 명세가 정확)
- **Type consistency**: `TraceEvent`·`Value`·`ObjectSnap`(Task 2) ↔ tracer.py 출력 키(Task 4) ↔ Scene(Task 5) ↔ PlaybackStep(Task 6) ↔ 컴포넌트 props(Task 8·9) 일치 확인. `valueLabel`은 expand.ts에서 export하여 VariablesView가 재사용
