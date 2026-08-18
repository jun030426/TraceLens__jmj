# Film Engine (3패스 무성영화 렌더러) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실행 트레이스를 자막 없이도 흐름이 읽히는 무성영화로 자동 변환하는 3패스 엔진 — 지속되는 무대 위에서 물체가 실제로 움직인다.

**Architecture:** 트레이스 전체를 미리 알고 있다는 이점을 살려, ①무대 짜기(등장인물·자리·크기를 결정적으로 계산) → ②콘티(사건을 모션 동사로 번역 + 리듬) → ③렌더(모든 등장인물을 처음부터 DOM에 올려두고 GSAP 마스터 타임라인이 나타내고 움직이고 지운다) 순서로 만든다. 프레임마다 다시 그리지 않으므로 물체가 시각적 정체성을 유지한다.

**Tech Stack:** TypeScript, React 19, SVG, GSAP Timeline, vitest. 기존 Tracer/Digest/Director 계층은 수정하지 않는다.

## Global Constraints

- 화면의 모든 값·순서는 TraceEvent에서만 나온다 (기획안 §1 값의 신뢰성)
- 기존 계약(TraceEvent / DigestSpan / Screenplay)은 변경하지 않는다
- 렌더러는 SVG + GSAP 단일. PixiJS는 투입하지 않는다
- 색은 기존 토큰만 사용: `--accent`, `--accent-wash`, `--panel`, `--sunken`, `--line`, `--line-strong`, `--ink`. 하드코딩 hex 금지
- 모션 정지 신호를 존중한다: `document.documentElement.dataset.still === 'true'`이면 타임라인을 끝 상태로 즉시 이동
- UI 문구는 한국어
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- 기존 테스트 114개가 계속 통과해야 한다

## File Structure

```
src/film/
  types.ts          StagePlan·Cast*·Shot·Motion 타입 (3패스 공용 계약)
  buildStage.ts     ①무대 짜기 — TraceEvent[] → StagePlan (슬롯 배정 포함)
  choreograph.ts    ②콘티 — TraceEvent[] + StagePlan + Digest → Shot[]
  layout.ts         StagePlan → 좌표 (무대 구역·슬롯 → x/y)
  WorldStage.tsx    ③렌더 — 지속 SVG 노드 + GSAP 마스터 타임라인
  useFilm.ts        타임라인 재생 제어 (play/pause/seek/timeScale)
src/fixtures/
  film-demo.trace.json   50줄 예제 트레이스 (scripts/gen_film_fixture.py 생성)
scripts/
  gen_film_fixture.py    50줄 데모 코드를 실행해 fixture 생성
```

기존 `src/components/Stage.tsx`와 `views/*`는 이 계획에서 **삭제하지 않는다** — Task 6에서 App이 WorldStage를 쓰도록 전환하고, 구 뷰는 보류 자산으로 남긴다.

---

### Task 1: 50줄 데모 fixture

**Files:**
- Create: `scripts/gen_film_fixture.py`
- Create(생성물): `src/fixtures/film-demo.trace.json`

**Interfaces:**
- Produces: `film-demo.trace.json` = `{ events: TraceEvent[], clipped: boolean, error: string|null }` — 이후 모든 태스크의 테스트 입력

데모 코드 요건: 50줄 내외이면서 (a) 리스트 생성·성장 (b) 별칭 `b = a` (c) 함수 호출·반환 (d) 재귀 (e) 10회 넘는 반복 (f) print 출력을 모두 포함한다. 그래야 모션 어휘 전체가 한 fixture에서 검증된다.

- [ ] **Step 1: 스크립트 작성** (`scripts/gen_film_fixture.py` 전체)

```python
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
```

- [ ] **Step 2: 실행하고 이벤트 수 확인**

Run: `PYTHONIOENCODING=utf-8 python scripts/gen_film_fixture.py`
Expected: `events: <300~900 사이 숫자> -> .../film-demo.trace.json`, clipped 없음

- [ ] **Step 3: Commit**

```bash
git add scripts/gen_film_fixture.py src/fixtures/film-demo.trace.json
git commit -m "feat: 50-line film demo fixture

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Pass 1 — 무대 짜기 (buildStage)

**Files:**
- Create: `src/film/types.ts`, `src/film/buildStage.ts`
- Test: `src/film/buildStage.test.ts`

**Interfaces:**
- Consumes: `TraceEvent`, `Value`, `ObjectSnap` (`src/trace/types.ts`), `buildSnapshots` (`src/trace/snapshots.ts`)
- Produces:

```ts
// src/film/types.ts — 이 태스크에서 만드는 부분
export type Lifespan = { from: number; to: number }

export type CastObject = {
  objectId: number
  type: string              // 'list' | 'dict' | 'set' | 클래스명
  life: Lifespan
  maxItems: number          // 이 객체가 가졌던 최대 원소·키 수
  changeCount: number
  referencedBy: string[]    // varKey 목록 — 2개 이상이면 별칭
  slot: number              // 무대 자리 번호 (구간 그래프 색칠 결과)
}

export type CastVariable = {
  varKey: string            // `${frameId}:${name}`
  frameId: number
  name: string
  life: Lifespan
  holdsRef: boolean         // 한 번이라도 객체를 가리킨 적 있는가
}

export type CastFrame = {
  frameId: number
  func: string
  parentFrameId: number | null
  life: Lifespan
  depth: number             // <module> = 0
  recursionIndex: number    // 조상 중 같은 func 개수 (재귀 몇 번째인지)
}

export type StagePlan = {
  objects: CastObject[]
  variables: CastVariable[]
  frames: CastFrame[]
  slotCount: number
  maxStackDepth: number
  maxListLength: number
  leadObjectId: number | null   // 주연: 변경 횟수 최다, 동률이면 더 오래 산 쪽
}
```

- `buildStage(events: TraceEvent[]): StagePlan`

**슬롯 배정 규칙**: 객체를 `life.from` 오름차순으로 정렬하고, 각 객체에 대해 이미 죽은(`life.to < 현재 life.from`) 객체가 쓰던 슬롯 중 가장 작은 번호를 재사용한다. 없으면 새 슬롯을 발급한다. (선형 스캔 레지스터 할당)

- [ ] **Step 1: 실패하는 테스트 작성** (`src/film/buildStage.test.ts` 전체)

```ts
import { describe, it, expect } from 'vitest'
import demo from '../fixtures/film-demo.trace.json'
import aliasing from '../fixtures/aliasing.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildStage } from './buildStage'

const demoEvents = (demo as { events: TraceEvent[] }).events
const aliasEvents = (aliasing as { events: TraceEvent[] }).events

describe('buildStage', () => {
  const plan = buildStage(demoEvents)

  it('등장인물을 모두 수집한다', () => {
    expect(plan.objects.length).toBeGreaterThan(0)
    expect(plan.variables.length).toBeGreaterThan(0)
    expect(plan.frames.length).toBeGreaterThan(0)
  })

  it('생몰 구간이 유효하다 (from <= to, 트레이스 범위 안)', () => {
    const last = demoEvents[demoEvents.length - 1].seq
    for (const o of plan.objects) {
      expect(o.life.from).toBeLessThanOrEqual(o.life.to)
      expect(o.life.to).toBeLessThanOrEqual(last)
    }
  })

  it('리스트의 최대 크기를 기록한다 (build_squares는 12칸까지 자람)', () => {
    expect(plan.maxListLength).toBeGreaterThanOrEqual(12)
  })

  it('재귀 프레임에 recursionIndex가 매겨진다 (total_of)', () => {
    const rec = plan.frames.filter(f => f.func === 'total_of')
    expect(rec.length).toBeGreaterThan(1)
    expect(Math.max(...rec.map(f => f.recursionIndex))).toBeGreaterThan(0)
  })

  it('최대 스택 깊이가 재귀를 반영한다', () => {
    expect(plan.maxStackDepth).toBeGreaterThanOrEqual(3)
  })

  it('주연을 고른다', () => {
    expect(plan.leadObjectId).not.toBeNull()
  })

  it('슬롯이 겹치지 않는다 — 같은 슬롯을 쓰는 객체는 생몰이 안 겹친다', () => {
    const bySlot = new Map<number, typeof plan.objects>()
    for (const o of plan.objects) bySlot.set(o.slot, [...(bySlot.get(o.slot) ?? []), o])
    for (const group of bySlot.values()) {
      const sorted = [...group].sort((a, b) => a.life.from - b.life.from)
      for (let i = 1; i < sorted.length; i++) {
        expect(sorted[i].life.from).toBeGreaterThan(sorted[i - 1].life.to)
      }
    }
    expect(plan.slotCount).toBeLessThanOrEqual(plan.objects.length)
  })

  it('별칭을 referencedBy로 잡는다', () => {
    const p = buildStage(aliasEvents)
    const shared = p.objects.find(o => o.referencedBy.length > 1)
    expect(shared).toBeDefined()
    expect(shared!.referencedBy.some(k => k.endsWith(':team_a'))).toBe(true)
    expect(shared!.referencedBy.some(k => k.endsWith(':team_b'))).toBe(true)
  })
})
```

- [ ] **Step 2: 실패 확인**

Run: `npx vitest run src/film/buildStage.test.ts`
Expected: FAIL — `Cannot find module './buildStage'`

- [ ] **Step 3: 구현** (`src/film/types.ts`는 위 Interfaces 블록 그대로, `src/film/buildStage.ts` 전체)

```ts
import type { TraceEvent } from '../trace/types'
import { buildSnapshots } from '../trace/snapshots'
import type { CastFrame, CastObject, CastVariable, StagePlan } from './types'

const varKeyOf = (frameId: number, name: string) => `${frameId}:${name}`

export function buildStage(events: TraceEvent[]): StagePlan {
  if (events.length === 0) {
    return { objects: [], variables: [], frames: [], slotCount: 0, maxStackDepth: 0, maxListLength: 0, leadObjectId: null }
  }
  const lastSeq = events[events.length - 1].seq

  // ── 객체 수집 ──
  const objAcc = new Map<number, { type: string; from: number; to: number; maxItems: number; changes: number; refs: Set<string> }>()
  for (const e of events) {
    for (const d of e.objectsDelta) {
      if (d.op !== 'set' || !d.obj) continue
      const size = (d.obj.items?.length ?? 0) + (d.obj.entries?.length ?? 0)
      const cur = objAcc.get(d.obj.id)
      if (cur) {
        cur.to = e.seq
        cur.maxItems = Math.max(cur.maxItems, size)
        cur.changes += 1
      } else {
        objAcc.set(d.obj.id, { type: d.obj.type, from: e.seq, to: e.seq, maxItems: size, changes: 1, refs: new Set() })
      }
    }
  }

  // ── 변수 수집 + 참조 관계 ──
  const varAcc = new Map<string, { frameId: number; name: string; from: number; to: number; holdsRef: boolean }>()
  for (const e of events) {
    for (const d of e.localsDelta) {
      const key = varKeyOf(e.frameId, d.name)
      const cur = varAcc.get(key)
      if (cur) cur.to = e.seq
      else varAcc.set(key, { frameId: e.frameId, name: d.name, from: e.seq, to: e.seq, holdsRef: false })
      if (d.op === 'set' && d.value?.k === 'ref') {
        varAcc.get(key)!.holdsRef = true
        const o = objAcc.get(d.value.id)
        if (o) {
          o.refs.add(key)
          o.to = Math.max(o.to, e.seq)
        }
      }
    }
  }

  // ── 프레임 수집 ──
  const frameAcc = new Map<number, { func: string; parent: number | null; from: number; to: number }>()
  for (const e of events) {
    const cur = frameAcc.get(e.frameId)
    if (cur) cur.to = e.seq
    else frameAcc.set(e.frameId, { func: e.func, parent: e.parentFrameId, from: e.seq, to: e.seq })
  }
  const frames: CastFrame[] = [...frameAcc.entries()].map(([frameId, f]) => {
    let depth = 0
    let recursionIndex = 0
    let p = f.parent
    const guard = new Set<number>()
    while (p !== null && p !== undefined && !guard.has(p)) {
      guard.add(p)
      depth += 1
      const parent = frameAcc.get(p)
      if (parent?.func === f.func) recursionIndex += 1
      p = parent?.parent ?? null
    }
    return { frameId, func: f.func, parentFrameId: f.parent, life: { from: f.from, to: f.to }, depth, recursionIndex }
  })

  // ── 슬롯 배정 (선형 스캔) ──
  const objects: CastObject[] = [...objAcc.entries()]
    .map(([objectId, o]) => ({
      objectId, type: o.type, life: { from: o.from, to: o.to },
      maxItems: o.maxItems, changeCount: o.changes, referencedBy: [...o.refs], slot: -1,
    }))
    .sort((a, b) => a.life.from - b.life.from)

  const freed: { slot: number; until: number }[] = []
  let slotCount = 0
  for (const o of objects) {
    const reusable = freed
      .filter(f => f.until < o.life.from)
      .sort((a, b) => a.slot - b.slot)[0]
    if (reusable) {
      o.slot = reusable.slot
      freed.splice(freed.indexOf(reusable), 1)
    } else {
      o.slot = slotCount++
    }
    freed.push({ slot: o.slot, until: o.life.to })
  }

  // ── 전체 지표 ──
  const snaps = buildSnapshots(events)
  const maxStackDepth = Math.max(...snaps.map(s => s.stack.length), 0)
  const maxListLength = Math.max(...objects.map(o => o.maxItems), 0)
  const lead = [...objects].sort(
    (a, b) => b.changeCount - a.changeCount || (b.life.to - b.life.from) - (a.life.to - a.life.from),
  )[0]

  const variables: CastVariable[] = [...varAcc.entries()].map(([varKey, v]) => ({
    varKey, frameId: v.frameId, name: v.name,
    life: { from: v.from, to: Math.min(v.to, lastSeq) }, holdsRef: v.holdsRef,
  }))

  return { objects, variables, frames, slotCount, maxStackDepth, maxListLength, leadObjectId: lead?.objectId ?? null }
}
```

- [ ] **Step 4: 통과 확인**

Run: `npx vitest run src/film/buildStage.test.ts`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/film
git commit -m "feat: pass 1 — stage planning with lifespans and slot allocation

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Pass 2 — 콘티 (choreograph)

**Files:**
- Modify: `src/film/types.ts` (Shot·Motion 타입 추가)
- Create: `src/film/choreograph.ts`
- Test: `src/film/choreograph.test.ts`

**Interfaces:**
- Consumes: `StagePlan`(Task 2), `TraceEvent`, `buildDigest`(`src/digest/buildDigest.ts`)
- Produces:

```ts
// src/film/types.ts 에 추가
export type Motion =
  | { v: 'enterVar'; varKey: string }
  | { v: 'setVar'; varKey: string; text: string }        // primitive 값 표시 문자열
  | { v: 'exitVar'; varKey: string }
  | { v: 'bind'; varKey: string; objectId: number; alias: boolean }
  | { v: 'enterObj'; objectId: number }
  | { v: 'grow'; objectId: number; index: number; text: string }
  | { v: 'setCell'; objectId: number; index: number; text: string }
  | { v: 'exitObj'; objectId: number }
  | { v: 'pushFrame'; frameId: number }
  | { v: 'popFrame'; frameId: number }
  | { v: 'stdout'; text: string }
  | { v: 'shake'; frameId: number }                       // 예외

export type Shot = {
  seq: number
  motions: Motion[]
  durationMs: number
  focus: { kind: 'object'; objectId: number } | { kind: 'frame'; frameId: number } | null
  timelapse?: number   // 이 샷이 N회 반복을 압축한 것이면 그 횟수
}
```

- `choreograph(events: TraceEvent[], plan: StagePlan): Shot[]`

**리듬 규칙 (사용자 확정)**: 반복 구간은 **처음 10회를 온전히** 재생하고, 그 이후는 하나의 timelapse 샷으로 압축한다. `buildDigest`가 주는 `iterations > 1`인 스팬을 반복 구간으로 본다.

**지속 시간**: 기본 520ms. `bind`에 alias가 있거나 `shake`가 있으면 1100ms(중요한 순간은 느리게). timelapse 샷은 900ms 고정.

- [ ] **Step 1: 실패하는 테스트 작성** (`src/film/choreograph.test.ts` 전체)

```ts
import { describe, it, expect } from 'vitest'
import demo from '../fixtures/film-demo.trace.json'
import aliasing from '../fixtures/aliasing.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildStage } from './buildStage'
import { choreograph } from './choreograph'

const demoEvents = (demo as { events: TraceEvent[] }).events
const aliasEvents = (aliasing as { events: TraceEvent[] }).events

describe('choreograph', () => {
  const shots = choreograph(demoEvents, buildStage(demoEvents))

  it('샷 seq가 단조 증가한다', () => {
    for (let i = 1; i < shots.length; i++) expect(shots[i].seq).toBeGreaterThan(shots[i - 1].seq)
  })

  it('원본보다 짧다 — 10회 규칙으로 압축된다', () => {
    expect(shots.length).toBeGreaterThan(0)
    expect(shots.length).toBeLessThan(demoEvents.length)
  })

  it('반복이 10회를 넘으면 timelapse 샷이 생긴다 (range(12))', () => {
    const lapse = shots.filter(s => s.timelapse && s.timelapse > 1)
    expect(lapse.length).toBeGreaterThan(0)
  })

  it('리스트가 자라는 순간에 grow 모션이 있다', () => {
    expect(shots.some(s => s.motions.some(m => m.v === 'grow'))).toBe(true)
  })

  it('함수 호출·반환이 프레임 모션으로 나온다', () => {
    expect(shots.some(s => s.motions.some(m => m.v === 'pushFrame'))).toBe(true)
    expect(shots.some(s => s.motions.some(m => m.v === 'popFrame'))).toBe(true)
  })

  it('출력이 stdout 모션으로 나온다', () => {
    expect(shots.some(s => s.motions.some(m => m.v === 'stdout'))).toBe(true)
  })

  it('별칭 순간은 alias 플래그와 긴 지속시간을 갖는다', () => {
    const aliasShots = choreograph(aliasEvents, buildStage(aliasEvents))
    const bind = aliasShots.flatMap(s => s.motions.map(m => ({ m, s }))).find(x => x.m.v === 'bind' && x.m.alias)
    expect(bind).toBeDefined()
    expect(bind!.s.durationMs).toBeGreaterThan(520)
  })

  it('모든 샷에 최소 하나의 모션이 있다 (빈 샷 금지)', () => {
    for (const s of shots) expect(s.motions.length).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 2: 실패 확인**

Run: `npx vitest run src/film/choreograph.test.ts`
Expected: FAIL — `Cannot find module './choreograph'`

- [ ] **Step 3: 구현** (`src/film/choreograph.ts` 전체)

```ts
import type { TraceEvent, Value, ObjectSnap } from '../trace/types'
import { buildDigest } from '../digest/buildDigest'
import type { Motion, Shot, StagePlan } from './types'

const BASE_MS = 520
const SLOW_MS = 1100
const LAPSE_MS = 900
const FULL_ITERATIONS = 10   // 사용자 확정: 10회는 온전히 보여준다

const shortText = (v: Value, objects: Map<number, ObjectSnap>): string => {
  if (v.k === 'prim') return v.v.length > 10 ? v.v.slice(0, 10) + '…' : v.v
  const o = objects.get(v.id)
  return o ? `${o.type}` : '객체'
}

export function choreograph(events: TraceEvent[], plan: StagePlan): Shot[] {
  const digest = buildDigest(events)
  const varsSeen = new Set<string>()
  const objsSeen = new Set<number>()
  const refCount = new Map<number, Set<string>>()
  const objects = new Map<number, ObjectSnap>()
  const prevSize = new Map<number, number>()

  // 반복 구간: 10회를 넘는 스팬의 "11회차부터 끝까지"를 압축 대상으로 표시
  const lapse: { from: number; to: number; count: number }[] = []
  for (const s of digest.spans) {
    if (!s.iterations || s.iterations <= FULL_ITERATIONS) continue
    const [a, b] = s.sourceSeqRange
    const perIter = Math.max(1, Math.floor((b - a + 1) / s.iterations))
    const cut = a + perIter * FULL_ITERATIONS
    if (cut < b) lapse.push({ from: cut, to: b, count: s.iterations - FULL_ITERATIONS })
  }
  const lapseAt = (seq: number) => lapse.find(l => seq >= l.from && seq <= l.to)

  const shots: Shot[] = []
  const consumed = new Set<number>()

  for (const e of events) {
    // 객체 상태를 계속 최신으로 유지 (텍스트 렌더용)
    for (const d of e.objectsDelta) {
      if (d.op === 'set' && d.obj) objects.set(d.obj.id, d.obj)
      else if (d.id !== undefined) objects.delete(d.id)
    }

    const inLapse = lapseAt(e.seq)
    if (inLapse) {
      if (consumed.has(inLapse.from)) continue
      consumed.add(inLapse.from)
      const target = [...objects.entries()].sort((a, b) => (b[1].items?.length ?? 0) - (a[1].items?.length ?? 0))[0]
      shots.push({
        seq: e.seq,
        motions: target
          ? [{ v: 'setCell', objectId: target[0], index: Math.max(0, (target[1].items?.length ?? 1) - 1), text: '…' }]
          : [{ v: 'stdout', text: '' }],
        durationMs: LAPSE_MS,
        focus: target ? { kind: 'object', objectId: target[0] } : null,
        timelapse: inLapse.count,
      })
      continue
    }

    const motions: Motion[] = []
    let slow = false

    if (e.kind === 'call') motions.push({ v: 'pushFrame', frameId: e.frameId })
    if (e.kind === 'return') motions.push({ v: 'popFrame', frameId: e.frameId })
    if (e.kind === 'exception') { motions.push({ v: 'shake', frameId: e.frameId }); slow = true }

    for (const d of e.objectsDelta) {
      if (d.op !== 'set' || !d.obj) continue
      const size = (d.obj.items?.length ?? 0) + (d.obj.entries?.length ?? 0)
      if (!objsSeen.has(d.obj.id)) {
        objsSeen.add(d.obj.id)
        motions.push({ v: 'enterObj', objectId: d.obj.id })
      } else {
        const before = prevSize.get(d.obj.id) ?? 0
        if (size > before) {
          const idx = size - 1
          const item = d.obj.items?.[idx]
          motions.push({ v: 'grow', objectId: d.obj.id, index: idx, text: item ? shortText(item, objects) : '' })
        } else if (size === before && size > 0) {
          const idx = Math.max(0, size - 1)
          const item = d.obj.items?.[idx]
          if (item) motions.push({ v: 'setCell', objectId: d.obj.id, index: idx, text: shortText(item, objects) })
        }
      }
      prevSize.set(d.obj.id, size)
    }

    for (const d of e.localsDelta) {
      const varKey = `${e.frameId}:${d.name}`
      if (d.op === 'delete') { motions.push({ v: 'exitVar', varKey }); varsSeen.delete(varKey); continue }
      if (!varsSeen.has(varKey)) { varsSeen.add(varKey); motions.push({ v: 'enterVar', varKey }) }
      if (d.value?.k === 'ref') {
        const holders = refCount.get(d.value.id) ?? new Set<string>()
        holders.add(varKey)
        refCount.set(d.value.id, holders)
        const alias = holders.size > 1
        if (alias) slow = true
        motions.push({ v: 'bind', varKey, objectId: d.value.id, alias })
      } else if (d.value) {
        motions.push({ v: 'setVar', varKey, text: shortText(d.value, objects) })
      }
    }

    if (e.stdout) motions.push({ v: 'stdout', text: e.stdout })

    if (motions.length === 0) continue

    const focusObj = motions.find(m => m.v === 'grow' || m.v === 'bind' || m.v === 'enterObj') as
      | { objectId: number } | undefined
    shots.push({
      seq: e.seq,
      motions,
      durationMs: slow ? SLOW_MS : BASE_MS,
      focus: focusObj
        ? { kind: 'object', objectId: focusObj.objectId }
        : { kind: 'frame', frameId: e.frameId },
    })
  }

  return shots
}
```

- [ ] **Step 4: 통과 확인**

Run: `npx vitest run src/film/choreograph.test.ts`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/film
git commit -m "feat: pass 2 — choreography with motion verbs and 10-iteration rhythm

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: 레이아웃 (무대 좌표)

**Files:**
- Create: `src/film/layout.ts`
- Test: `src/film/layout.test.ts`

**Interfaces:**
- Consumes: `StagePlan`(Task 2)
- Produces:

```ts
export type Rect = { x: number; y: number; w: number; h: number }
export type StageLayout = {
  width: number
  height: number
  varPos: Map<string, Rect>       // varKey → 이름표 자리
  objPos: Map<number, Rect>       // objectId → 상자 자리 (maxItems 기준 폭 예약)
  framePos: Map<number, Rect>     // frameId → 프레임 카드 자리
  cellW: number
}
export function layoutStage(plan: StagePlan): StageLayout
```

**구역 규칙**: 화면 1200×640 기준. 왼쪽 300px = 프레임 카드(깊이별 세로 계단), 가운데 이름표 열(x=340, 슬롯 순), 오른쪽 x=560부터 객체 상자(슬롯 번호 = 세로 줄). 객체 폭은 `maxItems × cellW`로 **미리 예약**해 자랄 때 밀리지 않게 한다. cellW는 maxListLength가 클수록 줄어든다(최소 26px).

- [ ] **Step 1: 실패하는 테스트 작성** (`src/film/layout.test.ts` 전체)

```ts
import { describe, it, expect } from 'vitest'
import demo from '../fixtures/film-demo.trace.json'
import type { TraceEvent } from '../trace/types'
import { buildStage } from './buildStage'
import { layoutStage } from './layout'

const events = (demo as { events: TraceEvent[] }).events
const plan = buildStage(events)
const L = layoutStage(plan)

describe('layoutStage', () => {
  it('모든 등장인물에 자리가 있다', () => {
    for (const o of plan.objects) expect(L.objPos.has(o.objectId)).toBe(true)
    for (const v of plan.variables) expect(L.varPos.has(v.varKey)).toBe(true)
    for (const f of plan.frames) expect(L.framePos.has(f.frameId)).toBe(true)
  })
  it('객체 폭이 최대 크기만큼 예약된다', () => {
    const big = plan.objects.find(o => o.maxItems >= 12)!
    expect(big).toBeDefined()
    expect(L.objPos.get(big.objectId)!.w).toBeGreaterThanOrEqual(big.maxItems * L.cellW)
  })
  it('같은 슬롯이라도 자리가 화면 안에 있다', () => {
    for (const r of L.objPos.values()) {
      expect(r.x).toBeGreaterThanOrEqual(0)
      expect(r.y + r.h).toBeLessThanOrEqual(L.height)
    }
  })
  it('셀 폭에 하한이 있다', () => {
    expect(L.cellW).toBeGreaterThanOrEqual(26)
  })
})
```

- [ ] **Step 2: 실패 확인**

Run: `npx vitest run src/film/layout.test.ts`
Expected: FAIL — `Cannot find module './layout'`

- [ ] **Step 3: 구현** (`src/film/layout.ts` 전체)

```ts
import type { StagePlan } from './types'

export type Rect = { x: number; y: number; w: number; h: number }
export type StageLayout = {
  width: number
  height: number
  varPos: Map<string, Rect>
  objPos: Map<number, Rect>
  framePos: Map<number, Rect>
  cellW: number
}

const W = 1200
const H = 640
const OBJ_X = 560
const VAR_X = 340
const ROW_H = 64

export function layoutStage(plan: StagePlan): StageLayout {
  const cellW = Math.max(26, Math.min(56, Math.floor((W - OBJ_X - 60) / Math.max(plan.maxListLength, 1))))

  const objPos = new Map<number, Rect>()
  for (const o of plan.objects) {
    const w = Math.max(120, o.maxItems * cellW + 16)
    objPos.set(o.objectId, {
      x: OBJ_X,
      y: 70 + o.slot * (ROW_H + 24),
      w: Math.min(w, W - OBJ_X - 24),
      h: ROW_H,
    })
  }

  const varPos = new Map<string, Rect>()
  const varOrder = [...plan.variables].sort((a, b) => a.life.from - b.life.from)
  varOrder.forEach((v, i) => {
    varPos.set(v.varKey, { x: VAR_X, y: 70 + i * 46, w: 168, h: 36 })
  })

  const framePos = new Map<number, Rect>()
  for (const f of plan.frames) {
    framePos.set(f.frameId, {
      x: 24 + f.depth * 18,
      y: H - 96 - f.depth * 68,
      w: 260 - f.depth * 18,
      h: 58,
    })
  }

  const maxObjBottom = Math.max(...[...objPos.values()].map(r => r.y + r.h), 0)
  const maxVarBottom = Math.max(...[...varPos.values()].map(r => r.y + r.h), 0)
  const height = Math.max(H, maxObjBottom + 40, maxVarBottom + 40)

  return { width: W, height, varPos, objPos, framePos, cellW }
}
```

- [ ] **Step 4: 통과 확인**

Run: `npx vitest run src/film/layout.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/film
git commit -m "feat: stage layout with reserved widths and slot rows

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Pass 3 — WorldStage 렌더 + 타임라인

**Files:**
- Create: `src/film/WorldStage.tsx`, `src/film/useFilm.ts`
- Modify: `src/stage.css` (film 클래스 추가)

**Interfaces:**
- Consumes: `StagePlan`·`Shot`(Task 2·3), `StageLayout`(Task 4)
- Produces:
  - `useFilm(shots: Shot[]): { time: number; playing: boolean; speed: number; play(): void; pause(): void; seek(shotIndex: number): void; setSpeed(x: number): void; index: number; register(tl: gsap.core.Timeline | null): void }`
  - `<WorldStage plan={StagePlan} layout={StageLayout} shots={Shot[]} film={ReturnType<typeof useFilm>} />`

**핵심 설계**: 모든 등장인물을 처음부터 SVG에 렌더하고 `opacity: 0`으로 숨긴다. GSAP 마스터 타임라인이 샷 순서대로 나타내고·움직이고·지운다. 재생/스크럽은 타임라인 시간 이동이므로 모션 도중에도 멈출 수 있다.

- [ ] **Step 1: useFilm 구현** (`src/film/useFilm.ts` 전체)

```ts
import { useCallback, useRef, useState } from 'react'
import type gsap from 'gsap'
import type { Shot } from './types'

export function useFilm(shots: Shot[]) {
  const tlRef = useRef<gsap.core.Timeline | null>(null)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)

  const register = useCallback((tl: gsap.core.Timeline | null) => {
    tlRef.current = tl
    if (tl) {
      tl.timeScale(speed)
      tl.eventCallback('onUpdate', () => {
        const t = tl.time()
        let acc = 0
        let i = 0
        for (let k = 0; k < shots.length; k++) {
          acc += shots[k].durationMs / 1000
          if (t <= acc) { i = k; break }
          i = k
        }
        setIndex(i)
      })
      tl.eventCallback('onComplete', () => setPlaying(false))
    }
  }, [shots, speed])

  const play = useCallback(() => {
    const tl = tlRef.current
    if (!tl) return
    if (tl.progress() >= 1) tl.progress(0)
    tl.play()
    setPlaying(true)
  }, [])

  const pause = useCallback(() => {
    tlRef.current?.pause()
    setPlaying(false)
  }, [])

  const seek = useCallback((shotIndex: number) => {
    const tl = tlRef.current
    if (!tl) return
    const clamped = Math.max(0, Math.min(shotIndex, shots.length - 1))
    const t = shots.slice(0, clamped).reduce((a, s) => a + s.durationMs / 1000, 0)
    tl.pause()
    tl.time(t)
    setIndex(clamped)
    setPlaying(false)
  }, [shots])

  const changeSpeed = useCallback((x: number) => {
    setSpeed(x)
    tlRef.current?.timeScale(x)
  }, [])

  return { index, playing, speed, play, pause, seek, setSpeed: changeSpeed, register }
}
```

- [ ] **Step 2: WorldStage 구현** (`src/film/WorldStage.tsx` 전체)

```tsx
import { useEffect, useRef } from 'react'
import gsap from 'gsap'
import type { Shot, StagePlan } from './types'
import type { StageLayout } from './layout'
import type { useFilm } from './useFilm'

type Props = {
  plan: StagePlan
  layout: StageLayout
  shots: Shot[]
  film: ReturnType<typeof useFilm>
}

const objSel = (id: number) => `[data-obj="${id}"]`
const cellSel = (id: number, i: number) => `[data-cell="${id}-${i}"]`
const varSel = (key: string) => `[data-var="${CSS.escape(key)}"]`
const frameSel = (id: number) => `[data-frame="${id}"]`
const ropeSel = (key: string, id: number) => `[data-rope="${CSS.escape(key)}-${id}"]`

export default function WorldStage({ plan, layout, shots, film }: Props) {
  const rootRef = useRef<SVGSVGElement | null>(null)
  const { register } = film

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const still = document.documentElement.dataset.still === 'true'
    const ctx = gsap.context(() => {
      // 시작 상태: 모두 숨김
      gsap.set('[data-obj], [data-var], [data-frame], [data-rope], [data-cell]', { opacity: 0 })
      const tl = gsap.timeline({ paused: true })

      for (const shot of shots) {
        const d = (shot.durationMs / 1000) * (still ? 0.001 : 1)
        const label = `s${shot.seq}`
        tl.addLabel(label)
        for (const m of shot.motions) {
          switch (m.v) {
            case 'enterVar':
              tl.to(varSel(m.varKey), { opacity: 1, duration: d * 0.6, ease: 'power2.out' }, label)
              break
            case 'setVar':
              tl.to(varSel(m.varKey), { opacity: 1, duration: d * 0.3 }, label)
              tl.call(() => {
                const el = root.querySelector(`${varSel(m.varKey)} .film-var-value`)
                if (el) el.textContent = m.text
              }, undefined, label)
              tl.fromTo(varSel(m.varKey), { scale: 1.14 }, { scale: 1, duration: d * 0.7, ease: 'back.out(2.4)', transformOrigin: 'center' }, label)
              break
            case 'exitVar':
              tl.to(varSel(m.varKey), { opacity: 0.18, duration: d * 0.5 }, label)
              break
            case 'bind':
              tl.to(objSel(m.objectId), { opacity: 1, duration: d * 0.4 }, label)
              tl.to(ropeSel(m.varKey, m.objectId), {
                opacity: 1, strokeDashoffset: 0,
                duration: m.alias ? d : d * 0.7, ease: 'power2.inOut',
              }, label)
              if (m.alias) {
                tl.fromTo(objSel(m.objectId), { scale: 1 }, { scale: 1.06, duration: d * 0.4, yoyo: true, repeat: 1, transformOrigin: 'center' }, label)
              }
              break
            case 'enterObj':
              tl.to(objSel(m.objectId), { opacity: 1, duration: d * 0.6, ease: 'power2.out' }, label)
              break
            case 'grow':
              tl.to(objSel(m.objectId), { opacity: 1, duration: d * 0.2 }, label)
              tl.call(() => {
                const el = root.querySelector(`${cellSel(m.objectId, m.index)} .film-cell-text`)
                if (el) el.textContent = m.text
              }, undefined, label)
              tl.fromTo(cellSel(m.objectId, m.index), { opacity: 0, scaleY: 0.2 }, { opacity: 1, scaleY: 1, duration: d, ease: 'back.out(2)', transformOrigin: 'center bottom' }, label)
              break
            case 'setCell':
              tl.call(() => {
                const el = root.querySelector(`${cellSel(m.objectId, m.index)} .film-cell-text`)
                if (el) el.textContent = m.text
              }, undefined, label)
              tl.fromTo(cellSel(m.objectId, m.index), { scale: 1.2 }, { scale: 1, duration: d, ease: 'back.out(2)', transformOrigin: 'center' }, label)
              break
            case 'exitObj':
              tl.to(objSel(m.objectId), { opacity: 0.15, duration: d }, label)
              break
            case 'pushFrame':
              tl.fromTo(frameSel(m.frameId), { opacity: 0, x: -26 }, { opacity: 1, x: 0, duration: d, ease: 'power3.out' }, label)
              break
            case 'popFrame':
              tl.to(frameSel(m.frameId), { opacity: 0, x: -26, duration: d, ease: 'power2.in' }, label)
              break
            case 'stdout':
              tl.call(() => {
                const el = root.querySelector('.film-stdout-text')
                if (el) el.textContent = m.text.trim().slice(0, 60)
              }, undefined, label)
              tl.fromTo('.film-stdout', { opacity: 0.5 }, { opacity: 1, duration: d, ease: 'power2.out' }, label)
              break
            case 'shake':
              tl.fromTo(frameSel(m.frameId), { x: 0 }, { x: 8, duration: d * 0.12, repeat: 5, yoyo: true }, label)
              break
          }
        }
        tl.to({}, { duration: d * 0.25 })   // 샷 사이 숨 고르기
      }

      register(tl)
      if (still) tl.progress(1)
    }, root)

    return () => { register(null); ctx.revert() }
  }, [shots, register])

  const objects = plan.objects
  const variables = plan.variables
  const frames = plan.frames

  return (
    <svg
      ref={rootRef}
      className="stage-svg film-stage"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      role="img"
      aria-label="코드 실행 무성영화"
    >
      {/* 프레임 카드 */}
      {frames.map(f => {
        const r = layout.framePos.get(f.frameId)!
        return (
          <g key={`f${f.frameId}`} data-frame={f.frameId}>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={10} fill="var(--panel)" stroke="var(--line-strong)" strokeWidth={1.2} />
            <text x={r.x + 14} y={r.y + 34} className="svg-name">
              {f.func === '<module>' ? '프로그램' : `${f.func}()`}
            </text>
          </g>
        )
      })}

      {/* 끈: 변수 → 객체 */}
      {variables.flatMap(v =>
        objects.map(o => {
          const a = layout.varPos.get(v.varKey)!
          const b = layout.objPos.get(o.objectId)!
          const x1 = a.x + a.w
          const y1 = a.y + a.h / 2
          const x2 = b.x
          const y2 = b.y + b.h / 2
          return (
            <path
              key={`r${v.varKey}-${o.objectId}`}
              data-rope={`${v.varKey}-${o.objectId}`}
              d={`M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={2.4}
              strokeLinecap="round"
            />
          )
        }),
      )}

      {/* 객체 상자 */}
      {objects.map(o => {
        const r = layout.objPos.get(o.objectId)!
        const cells = Math.max(o.maxItems, 1)
        return (
          <g key={`o${o.objectId}`} data-obj={o.objectId}>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={10} fill="var(--sunken)" stroke="var(--line)" strokeWidth={1.4} />
            <text x={r.x + 4} y={r.y - 8} className="svg-type">{o.type}</text>
            {Array.from({ length: cells }, (_, i) => (
              <g key={i} data-cell={`${o.objectId}-${i}`}>
                <rect x={r.x + 8 + i * layout.cellW} y={r.y + 8} width={layout.cellW - 6} height={r.h - 16} rx={5} fill="var(--panel)" stroke="var(--line-strong)" strokeWidth={1} />
                <text className="film-cell-text svg-value" x={r.x + 8 + i * layout.cellW + (layout.cellW - 6) / 2} y={r.y + r.h / 2 + 5} textAnchor="middle" />
              </g>
            ))}
          </g>
        )
      })}

      {/* 이름표 */}
      {variables.map(v => {
        const r = layout.varPos.get(v.varKey)!
        return (
          <g key={`v${v.varKey}`} data-var={v.varKey}>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={r.h / 2} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.4} />
            <text x={r.x + 14} y={r.y + 24} className="svg-name">{v.name}</text>
            <text className="film-var-value svg-value" x={r.x + r.w - 14} y={r.y + 24} textAnchor="end" />
          </g>
        )
      })}

      {/* 콘솔 */}
      <g className="film-stdout">
        <rect x={24} y={layout.height - 52} width={layout.width - 48} height={36} rx={8} fill="var(--sunken)" stroke="var(--line)" strokeWidth={1} />
        <text x={38} y={layout.height - 28} className="svg-type">출력</text>
        <text className="film-stdout-text svg-value" x={92} y={layout.height - 28} />
      </g>
    </svg>
  )
}
```

- [ ] **Step 3: 스타일 추가** (`src/stage.css` 끝에 append)

```css
/* 무성영화 무대 */
.film-stage { background: var(--sunken); border-radius: 14px; }
.film-stage text { pointer-events: none; }
.film-cell-text { font-size: 12px; }
```

- [ ] **Step 4: 타입체크**

Run: `npx tsc -b`
Expected: 오류 없음 (exit 0)

- [ ] **Step 5: Commit**

```bash
git add src/film src/stage.css
git commit -m "feat: pass 3 — persistent world stage driven by a GSAP master timeline

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: App 연결 + 브라우저 검증

**Files:**
- Modify: `src/App.tsx`

**Interfaces:**
- Consumes: `buildStage`(Task 2), `choreograph`(Task 3), `layoutStage`(Task 4), `WorldStage`·`useFilm`(Task 5)

App은 실행 결과가 나오면 기존 `steps` 대신 **film 경로**를 쓴다: `buildStage` → `layoutStage` → `choreograph` → `WorldStage`. 자막(narration)은 기존 Screenplay에서 계속 가져오되, 샷 인덱스로 매핑한다. PlayerBar·Inspector는 그대로 두고 `film`의 index/seek을 연결한다.

- [ ] **Step 1: App에 film 파이프라인 배선**

`RunArtifacts`에 필드를 추가한다:

```ts
import { buildStage } from './film/buildStage'
import { layoutStage, type StageLayout } from './film/layout'
import { choreograph } from './film/choreograph'
import type { StagePlan, Shot } from './film/types'
import WorldStage from './film/WorldStage'
import { useFilm } from './film/useFilm'

type RunArtifacts = {
  steps: PlaybackStep[]
  snaps: Snapshot[]
  screenplay: Screenplay
  clipped: boolean
  error?: string
  directorMode: DirectorMode
  plan: StagePlan
  layout: StageLayout
  shots: Shot[]
}
```

`executeRun` 안에서 `expandScreenplay` 직후에 계산해 `setRun`에 함께 담는다:

```ts
const plan = buildStage(result.events)
const layout = layoutStage(plan)
const shots = choreograph(result.events, plan)
setRun({ steps: expanded, snaps, screenplay, clipped: result.clipped, error: result.error, directorMode, plan, layout, shots })
```

- [ ] **Step 2: 렌더 교체**

`usePlayback(steps)` 호출을 `useFilm(run?.shots ?? [])`로 바꾸고, 스테이지 자리에 WorldStage를 넣는다:

```tsx
const film = useFilm(run?.shots ?? [])
const currentShot = run?.shots[film.index]
const currentSnap = currentShot ? bySeq.get(currentShot.seq) : undefined
```

```tsx
{run ? (
  <WorldStage plan={run.plan} layout={run.layout} shots={run.shots} film={film} />
) : (
  <div className="stage-empty">왼쪽에 파이썬 코드를 붙여넣고 실행을 누르면, 그 실행이 남긴 기록이 여기에 그려집니다</div>
)}
```

자막은 현재 샷의 seq에 가장 가까운 step에서 가져온다:

```tsx
const narration = currentShot
  ? [...steps].reverse().find(s => s.seq <= currentShot.seq)?.narration ?? ''
  : 'Run을 누르면 설명이 시작됩니다'
```

PlayerBar에는 `film.index`, `film.playing`, `film.speed`, `film.play`, `film.pause`, `film.seek`, `film.setSpeed`를 넘기고 `steps` 대신 `run.shots.length` 기준으로 표시한다.

- [ ] **Step 3: 타입체크 + 전체 테스트**

Run: `npx tsc -b && npx vitest run`
Expected: tsc exit 0, 기존 114개 + 신규 20개 = 134개 전부 통과

- [ ] **Step 4: 브라우저 검증**

dev 서버에서 `/app`에 fixture와 같은 50줄 데모 코드를 붙여넣고 Run. 확인 항목:

| 확인 | 기대 |
|---|---|
| 물체 지속성 | 리스트 상자가 영화 내내 같은 자리에 있고, 칸이 하나씩 자란다 |
| 자리 예약 | 12칸까지 자라는 동안 상자가 밀리거나 재배치되지 않는다 |
| 끈 묶기 | `shared = squares`에서 두 번째 끈이 같은 상자로 연결된다 |
| 프레임 | 함수 호출 시 카드가 왼쪽에서 들어오고 반환 시 나간다 |
| 재생 제어 | 재생/일시정지/스크럽이 모션 도중에도 부드럽게 동작한다 |
| 자막 끄기 테스트 | 자막을 가리고 봐도 "리스트가 자란다 → 두 이름이 같은 걸 가리킨다 → 함수가 오갔다"가 읽힌다 |

- [ ] **Step 5: Commit**

```bash
git add src/App.tsx
git commit -m "feat: wire film engine into app — world stage replaces per-step redraw

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review 결과

- **Spec coverage**: 3패스 구조(Task 2·3·5), 물체 지속성(Task 5 — 전원 사전 마운트), 자리 예약(Task 4), 10회 규칙(Task 3 `FULL_ITERATIONS`), 기본 4동사 + 특화 동사(Task 3 Motion 타입 — enter/set/exit/push·pop + grow·bind·stdout·shake), 50줄 예제(Task 1), 정지 신호 존중(Task 5), 폴백 철학(콘티 없어도 무대는 계산되므로 Task 2·4는 AI 없이 항상 성공). **카메라(줌·이동)는 이 계획에 포함하지 않는다** — 무대·모션·리듬이 검증된 뒤 다음 계획에서 다룬다. 이유: 카메라는 레이아웃이 안정된 뒤에 얹어야 값이 있고, 먼저 넣으면 세 가지가 동시에 흔들려 원인 분리가 안 된다.
- **Placeholder scan**: 통과 — 모든 스텝에 실제 코드·명령·기대 출력 포함
- **Type consistency**: `StagePlan`·`CastObject.slot`(Task 2) → `layoutStage`(Task 4)가 소비, `Shot`·`Motion`(Task 3) → `WorldStage`(Task 5)가 소비, `useFilm` 반환 타입(Task 5) → App(Task 6)이 소비. `varKey` 형식 `${frameId}:${name}`이 Task 2·3·4·5에서 동일하게 쓰임
