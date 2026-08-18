# 피드백 2차 반영 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 팀 피드백 10항목을 반영 — Ctrl+Enter 실행, 오류 시각화, 무대 줌, 대표 시각화 어휘(칸 번호·반복 배지·비교·스왑), AI 연출 비차단·지연 최적화, 장면 단위 폴백(salvage)과 AI 디테일 계층(decorate).

**Architecture:** 규칙 기반 영상이 항상 완성되는 Core를 유지한 채, ① 모션 어휘를 문법 요소별 대표 시각화로 확장(전부 트레이스에서 결정적 도출)하고 ② AI 대본을 비차단 백그라운드로 받아 자막·챕터·완급 장식만 점진 적용한다. 설계 근거: [2026-08-16-feedback-round2-design.md](../specs/2026-08-16-feedback-round2-design.md)

**Tech Stack:** TypeScript, React 19, SVG + GSAP Timeline, vitest, Gemini API(v1beta)

## Global Constraints

- 화면의 모든 값·순서는 TraceEvent에서만 나온다 (값의 신뢰성). compare의 참/거짓은 트레이스 값에 대한 산술이지 생성이 아니다
- LLM은 spanRef 선택 + primitive/pacing/focus/narration만 — 좌표·값·효과를 생성하지 않는다
- 색·타이포는 기존 토큰만 사용 (`--accent`, `--accent-wash`, `--panel`, `--sunken`, `--line`, `--line-strong`, `--ink*`, `--d-*`, `--t-*`). 하드코딩 hex·literal font-size 금지
- verdict 3색(ok/warn/stop)은 무대 그림 안에서 쓰지 않는다 (Drawn-State Rule)
- UI 문구는 한국어
- 기존 테스트 135개 통과 유지. 커밋 메시지 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 각 태스크 후 `npx tsc -b && npx vitest run` 통과 확인 후 커밋

## File Structure

```
src/film/types.ts        Motion 어휘 확장 (raise·loop·loopEnd·compare·swap·shrink·spotlight)
src/film/choreograph.ts  signature +code?, 정밀 칸 diff, loop/compare/swap/raise 감지
src/film/WorldStage.tsx  카메라(줌·팬), 칸 번호, 오류 스트립, 반복 배지, 비교 칩, 스왑 렌더
src/film/decorate.ts     (신규) AI 대본 → 완급·스포트라이트 장식
src/director/resolver.ts salvageScreenplay (장면 단위 부분 수용 + 규칙 충전)
src/director/llmDirector.ts generateScreenplayWithSalvage, 프롬프트 슬림화
src/director/gemini.ts   thinkingBudget 0, 20초 타임아웃
src/App.tsx              Ctrl+Enter, 비차단 AI, 위치 복원, 오류 장면, 상태 태그
src/routes/Demo.tsx      choreograph에 fixture.code 전달
src/ui/app.css           .film-viewport/.film-zoom/.stage-error/.svg-index 등 (토큰 소비만)
src/routes/Help.tsx      새 시각화 어휘 문구 반영
```

---

### Task 0: 작업 트리 정리 커밋

이전 세션의 미커밋 변경(stage.css 삭제 → app.css로 이동)이 트리에 남아 있다. DESIGN.md에 이미 문서화된 결정이므로 그대로 커밋한다.

- [ ] **Step 1: stage.css를 참조하는 곳이 없는지 확인**

Run: `grep -rn "stage.css" src/ index.html`
Expected: 결과 없음

- [ ] **Step 2: 빌드 확인 후 커밋**

Run: `npx tsc -b && npx vitest run` → 135 passed

```bash
git add -A src/stage.css src/ui/app.css
git commit -m "refactor: fold film stage styles into app.css tokens, delete stage.css"
```

---

### Task 1: Ctrl+Enter 실행

**Files:**
- Modify: `src/App.tsx`

**Interfaces:**
- Produces: 에디터 안에서 Ctrl+Enter(mac Cmd+Enter) → `executeRun()`. 로딩 중·빈 코드면 무시.

- [ ] **Step 1: executeRun 상단 가드 + ref 배선**

`App()` 안, `executeRun` 정의를 다음으로 바꾼다 (가드 2줄 추가):

```ts
const executeRun = async () => {
  if (loading !== null || !code.trim()) return   // 버튼 disabled를 우회하는 단축키 경로 가드
  const found = preflight(code)
  ...이하 기존과 동일...
}
```

`executeRun` 정의 **아래**에 최신 클로저를 담는 ref를 추가한다 (Monaco 커맨드는 마운트 시점 클로저만 잡으므로):

```ts
const executeRunRef = useRef<() => void>(() => {})
useEffect(() => { executeRunRef.current = executeRun })
```

- [ ] **Step 2: Monaco 커맨드 등록 + 힌트 문구**

`handleEditorMount` 마지막에:

```ts
editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => executeRunRef.current())
```

runbar 힌트 문구 교체:

```tsx
{code.trim() ? '표준 라이브러리 중심 · 단일 파일 · Ctrl+Enter 실행' : '파이썬 코드를 붙여넣으세요'}
```

- [ ] **Step 3: 검증 + 커밋**

Run: `npx tsc -b && npx vitest run` → 통과. 브라우저 확인은 Task 11에서 일괄.

```bash
git add src/App.tsx
git commit -m "feat: run on Ctrl+Enter inside the editor"
```

---

### Task 2: 오류 시각화 — raise 모션 + 오류 스트립 + 구문 오류 장면

**Files:**
- Modify: `src/film/types.ts`, `src/film/choreograph.ts`, `src/film/WorldStage.tsx`, `src/App.tsx`, `src/ui/app.css`
- Test: `src/film/choreograph.test.ts`

**Interfaces:**
- Produces: `Motion` 에 `{ v: 'raise'; frameId: number; text: string }`. exception 이벤트 → shake + raise(오류명 표시, 끝까지 유지). 이벤트 0개 + error → 무대에 `.stage-error` DOM 카드.

- [ ] **Step 1: 실패하는 테스트** (`choreograph.test.ts`에 추가)

```ts
const P = (v: string, t = 'int') => ({ k: 'prim' as const, v, t })

describe('choreograph: raise', () => {
  const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
    seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
    causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...over,
  })
  it('예외 이벤트에 raise 모션이 나오고 오류명이 담긴다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: P('1') }] }, 1),
      ev({ kind: 'exception', error: 'IndexError: list index out of range', observedAtLine: 2 }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const raise = shots.flatMap(s => s.motions).find(m => m.v === 'raise')
    expect(raise).toBeDefined()
    expect((raise as { text: string }).text).toContain('IndexError')
  })
})
```

- [ ] **Step 2: 실패 확인** — `npx vitest run src/film/choreograph.test.ts` → FAIL

- [ ] **Step 3: 구현**

`types.ts` Motion에 추가: `| { v: 'raise'; frameId: number; text: string }`

`choreograph.ts` exception 분기:

```ts
if (e.kind === 'exception') {
  motions.push({ v: 'shake', frameId: e.frameId })
  motions.push({ v: 'raise', frameId: e.frameId, text: e.error ?? '예외 발생' })
  slow = true
}
```

`WorldStage.tsx` — 초기 숨김 목록 확장:

```ts
gsap.set(root.querySelectorAll('[data-obj], [data-var], [data-frame], [data-rope], [data-cell], .film-error'), { opacity: 0 })
```

콘솔(`film-stdout`) 그룹 위쪽, SVG 최상단에 스트립 렌더 추가 (레이아웃 첫 행이 y=70이므로 y=14는 비어 있다):

```tsx
<g className="film-error">
  <rect x={24} y={14} width={layout.width - 48} height={34} rx={8} fill="var(--panel)" stroke="var(--accent)" strokeWidth={1.4} />
  <text className="svg-type" x={40} y={36}>오류</text>
  <text className="film-error-text svg-name" x={92} y={36} />
</g>
```

타임라인 케이스:

```ts
case 'raise': {
  const text = m.text
  tl.call(() => {
    const el = root.querySelector('.film-error-text')
    if (el) el.textContent = text.slice(0, 80)
  }, undefined, label)
  tl.fromTo(q('.film-error')!, { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: d * 0.5, ease: 'power3.out' }, label)
  break
}
```

`App.tsx` 스테이지 분기 — 이벤트 0개 오류를 빈 화면 대신 오류 장면으로:

```tsx
{run && shots.length > 0 ? (
  <WorldStage plan={run.plan} layout={run.layout} shots={shots} film={film} />
) : run?.error ? (
  <div className="stage-error" role="alert">
    <span className="tl-label">실행이 여기서 멈췄습니다</span>
    <code className="tl-mono">{run.error}</code>
  </div>
) : (
  <Stage snapshot={currentSnap} step={currentStep} />
)}
```

`app.css` stage 구역에 추가:

```css
.stage-error {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 220px;
  padding: 24px;
  text-align: center;
}
.stage-error code {
  max-width: 60ch;
  white-space: pre-wrap;
  word-break: break-all;
}
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `npx tsc -b && npx vitest run` → 전체 통과

```bash
git add src/film src/App.tsx src/ui/app.css
git commit -m "feat: errors are content — raise strip on stage, error scene for zero-event runs"
```

---

### Task 3: 무대 카메라 — 휠 줌 · 드래그 팬 · 확대/축소/맞춤 버튼

**Files:**
- Modify: `src/film/WorldStage.tsx`, `src/ui/app.css`

**Interfaces:**
- Produces: WorldStage 루트가 `<div class="film-viewport">`(svg + 버튼 클러스터)로 바뀜. 배율 0.4~3, 새 실행(plan 변경) 시 리셋. GSAP 타깃은 카메라 `<g>` 자식이라 간섭 없음.

- [ ] **Step 1: 카메라 상태·핸들러 구현** (WorldStage 컴포넌트에 추가)

```tsx
const FIT = { k: 1, tx: 0, ty: 0 }
const [cam, setCam] = useState(FIT)
const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)

// 새 실행에서만 리셋 — AI 장식은 shots만 바꾸므로 plan을 키로 쓴다
useEffect(() => { setCam(FIT) }, [plan])

const clampK = (k: number) => Math.min(3, Math.max(0.4, k))
const zoomBy = (f: number) => setCam(c => ({ ...c, k: clampK(c.k * f) }))

// React 합성 wheel은 passive — preventDefault가 안 먹히므로 네이티브로 단다
useEffect(() => {
  const svg = rootRef.current
  if (!svg) return
  const onWheel = (ev: WheelEvent) => {
    ev.preventDefault()
    setCam(c => ({ ...c, k: clampK(c.k * (ev.deltaY < 0 ? 1.12 : 0.9)) }))
  }
  svg.addEventListener('wheel', onWheel, { passive: false })
  return () => svg.removeEventListener('wheel', onWheel)
}, [])

const unitsPerPx = () => {
  const rect = rootRef.current?.getBoundingClientRect()
  if (!rect || rect.width === 0) return 1
  return Math.max(layout.width / rect.width, layout.height / rect.height)
}
const onPointerDown = (ev: React.PointerEvent<SVGSVGElement>) => {
  if (cam.k === 1) return
  ev.currentTarget.setPointerCapture(ev.pointerId)
  dragRef.current = { x: ev.clientX, y: ev.clientY, tx: cam.tx, ty: cam.ty }
}
const onPointerMove = (ev: React.PointerEvent<SVGSVGElement>) => {
  const drag = dragRef.current
  if (!drag) return
  const u = unitsPerPx()
  setCam(c => ({ ...c, tx: drag.tx + (ev.clientX - drag.x) * u, ty: drag.ty + (ev.clientY - drag.y) * u }))
}
const onPointerUp = () => { dragRef.current = null }

const cx = layout.width / 2
const cy = layout.height / 2
const camTransform = `translate(${cam.tx + cx * (1 - cam.k)} ${cam.ty + cy * (1 - cam.k)}) scale(${cam.k})`
```

- [ ] **Step 2: 렌더 구조 변경**

기존 `<svg>…</svg>` 반환을 다음으로 감싼다 — 내용 전체를 카메라 `<g>` 안으로:

```tsx
return (
  <div className="film-viewport">
    <svg
      ref={rootRef}
      className="stage-svg film-stage"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      role="img"
      aria-label="코드 실행 무성영화"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
      style={{ cursor: cam.k !== 1 ? 'grab' : 'default' }}
    >
      <g transform={camTransform}>
        {/* …기존 내용 전부 (frames / ropes / objects / vars / film-error / film-stdout)… */}
      </g>
    </svg>
    <div className="film-zoom" role="group" aria-label="확대 조절">
      <button type="button" className="tl-btn tl-btn--quiet tl-btn--sm" onClick={() => zoomBy(0.8)} aria-label="축소">−</button>
      <button type="button" className="tl-btn tl-btn--quiet tl-btn--sm" onClick={() => setCam(FIT)} aria-label="화면 맞춤">맞춤</button>
      <button type="button" className="tl-btn tl-btn--quiet tl-btn--sm" onClick={() => zoomBy(1.25)} aria-label="확대">+</button>
    </div>
  </div>
)
```

import에 `useState` 추가.

- [ ] **Step 3: CSS** (`app.css` stage 구역)

```css
.film-viewport {
  position: relative;
  width: 100%;
  height: 100%;
}
.film-viewport svg {
  touch-action: none;
}
.film-zoom {
  position: absolute;
  right: 10px;
  bottom: 10px;
  display: flex;
  gap: 4px;
}
.film-zoom .tl-btn {
  min-width: 34px;
  padding: 0 8px;
}
```

데모 라우트(`src/routes/demo.css`)의 무대 컨테이너가 svg 고유 비율로 높이를 잡고 있으면 `.film-viewport` 100% 높이가 무너진다 — 구현 시 demo.css를 확인하고, 필요하면 데모 무대 컨테이너에 고정 높이(또는 aspect-ratio)를 준다.

- [ ] **Step 4: 검증 + 커밋**

Run: `npx tsc -b && npx vitest run` → 통과. 줌·팬 동작은 Task 11 브라우저 검증.

```bash
git add src/film/WorldStage.tsx src/ui/app.css src/routes/demo.css
git commit -m "feat: stage camera — wheel zoom, drag pan, fit controls"
```

---

### Task 4: 칸 번호 + 정밀 칸 diff (+shrink)

**Files:**
- Modify: `src/film/types.ts`, `src/film/choreograph.ts`, `src/film/WorldStage.tsx`, `src/ui/app.css`
- Test: `src/film/choreograph.test.ts`

**Interfaces:**
- Produces: `Motion`에 `{ v: 'shrink'; objectId: number; index: number }`. choreograph 내부가 `prevSize`(크기만) 대신 `prevTexts: Map<objectId, string[]>`(칸별 표시 문자열)를 유지 — "같은 크기 + 내용 변경"에서 **바뀐 인덱스들**을 정확히 setCell (기존: 마지막 칸만). 크기가 줄면 사라진 칸을 shrink. Task 7의 스왑 감지가 이 diff를 소비한다.
- 렌더: 각 칸 아래 인덱스 번호 (`svg-index`, 칸과 함께 나타남).

- [ ] **Step 1: 실패하는 테스트 추가**

```ts
describe('choreograph: 정밀 칸 diff', () => {
  const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
    seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
    causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...over,
  })
  const listSet = (items: string[]) => ({
    op: 'set' as const, obj: { id: 1, type: 'list', items: items.map(v => P(v)) },
  })
  it('크기가 같아도 바뀐 칸을 전부 짚는다 (0번과 2번)', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [listSet(['1', '2', '3'])] }, 1),
      ev({ objectsDelta: [listSet(['9', '2', '7'])] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const cells = shots.flatMap(s => s.motions).filter(m => m.v === 'setCell') as { index: number; text: string }[]
    expect(cells.map(c => [c.index, c.text])).toEqual(expect.arrayContaining([[0, '9'], [2, '7']]))
    expect(cells.some(c => c.index === 1)).toBe(false)
  })
  it('크기가 줄면 사라진 칸에 shrink가 나온다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [listSet(['1', '2'])] }, 1),
      ev({ objectsDelta: [listSet(['1'])] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const shrink = shots.flatMap(s => s.motions).find(m => m.v === 'shrink')
    expect(shrink).toMatchObject({ objectId: 1, index: 1 })
  })
})
```

- [ ] **Step 2: 실패 확인** — shrink 미구현·diff는 마지막 칸만 짚으므로 FAIL

- [ ] **Step 3: 구현**

`types.ts`: `| { v: 'shrink'; objectId: number; index: number }`

`choreograph.ts` — `const prevSize = new Map<number, number>()` 를 `const prevTexts = new Map<number, string[]>()` 로 교체하고 objectsDelta 처리 블록을 다음으로 재작성:

```ts
for (const d of e.objectsDelta) {
  if (d.op !== 'set' || !d.obj) continue
  const size = (d.obj.items?.length ?? 0) + (d.obj.entries?.length ?? 0)
  const cellTextAt = (idx: number): string | null => {
    const item = d.obj?.items?.[idx]
    if (item) return shortText(item, objects)
    const entry = d.obj?.entries?.[idx]
    if (entry) return `${entry[0]}: ${shortText(entry[1], objects)}`
    return null
  }
  const texts = Array.from({ length: size }, (_, i) => cellTextAt(i) ?? '')
  const prev = prevTexts.get(d.obj.id)

  if (!prev) {
    objsSeen.add(d.obj.id)
    motions.push({ v: 'enterObj', objectId: d.obj.id })
    for (let i = 0; i < size; i++) motions.push({ v: 'grow', objectId: d.obj.id, index: i, text: texts[i] })
  } else if (size > prev.length) {
    for (let i = 0; i < prev.length; i++)
      if (texts[i] !== prev[i]) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
    for (let i = prev.length; i < size; i++) motions.push({ v: 'grow', objectId: d.obj.id, index: i, text: texts[i] })
  } else if (size === prev.length && size > 0) {
    const changed: number[] = []
    for (let i = 0; i < size; i++) if (texts[i] !== prev[i]) changed.push(i)
    for (const i of changed) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
  } else if (size < prev.length) {
    for (let i = 0; i < size; i++)
      if (texts[i] !== prev[i]) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
    for (let i = size; i < prev.length; i++) motions.push({ v: 'shrink', objectId: d.obj.id, index: i })
  }
  prevTexts.set(d.obj.id, texts)
}
```

(`objsSeen`은 존재 판단을 `prev` 유무로 대체할 수 있으나 다른 곳에서 안 쓰므로 함께 정리해도 된다 — 컴파일러가 알려주는 대로.)

`WorldStage.tsx` 칸 그룹에 번호 추가 (칸과 함께 페이드인되도록 `data-cell` 그룹 안):

```tsx
<g key={i} data-cell={`${o.objectId}-${i}`}>
  <rect … 기존 … />
  <text className="film-cell-text svg-value" … 기존 … />
  <text
    className="svg-index"
    x={r.x + 8 + i * layout.cellW + (layout.cellW - 6) / 2}
    y={r.y + r.h + 14}
    textAnchor="middle"
  >
    {i}
  </text>
</g>
```

타임라인 케이스:

```ts
case 'shrink': {
  const el = q(cellSel(m.objectId, m.index))
  if (el) tl.to(el, { opacity: 0, scale: 0.6, duration: d * 0.5, ease: 'power2.in', transformOrigin: 'center' }, label)
  break
}
```

`app.css`:

```css
.svg-index {
  fill: var(--ink-3);
  font-family: var(--mono);
  font-size: var(--d-xs);
}
```

- [ ] **Step 4: 통과 확인 + 커밋** — `npx tsc -b && npx vitest run`

```bash
git add src/film src/ui/app.css
git commit -m "feat: cell index numerals + exact per-cell diff with shrink"
```

---

### Task 5: 반복 배지 — "반복문이 돌고 있다"의 상시 표시

**Files:**
- Modify: `src/film/types.ts`, `src/film/choreograph.ts`, `src/film/WorldStage.tsx`
- Test: `src/film/choreograph.test.ts`

**Interfaces:**
- Produces: `Motion`에 `{ v: 'loop'; text: string }`, `{ v: 'loopEnd' }`. digest 스팬(iterations>1)의 헤더 라인(=`s.lines[1]`, 접힘 시작 이벤트의 관측 라인) 재방문마다 "반복 N회차 / 총 M회", 압축 샷에 "남은 X회 빨리감기", 스팬 이탈 시 loopEnd.

- [ ] **Step 1: 실패하는 테스트** (film-demo fixture는 range(12) 루프 포함)

```ts
describe('choreograph: 반복 배지', () => {
  const shots = choreograph(demoEvents, buildStage(demoEvents))
  const all = shots.flatMap(s => s.motions)
  it('반복 중에 회차 배지가 나온다', () => {
    const loops = all.filter(m => m.v === 'loop') as { text: string }[]
    expect(loops.some(l => l.text.includes('회차'))).toBe(true)
  })
  it('압축 샷은 빨리감기 문구를 단다', () => {
    const loops = all.filter(m => m.v === 'loop') as { text: string }[]
    expect(loops.some(l => l.text.includes('빨리감기'))).toBe(true)
  })
  it('반복이 끝나면 배지가 내려간다', () => {
    expect(all.some(m => m.v === 'loopEnd')).toBe(true)
  })
})
```

- [ ] **Step 2: 실패 확인** → FAIL

- [ ] **Step 3: 구현**

`types.ts`: `| { v: 'loop'; text: string } | { v: 'loopEnd' }`

`choreograph.ts` — digest 계산 직후:

```ts
// 접힘은 3회차 방문부터 시작되므로 seen은 2에서 출발한다
const loopSpans = digest.spans
  .filter(s => (s.iterations ?? 0) > 1)
  .map(s => ({ from: s.sourceSeqRange[0], to: s.sourceSeqRange[1], total: s.iterations!, headerLine: s.lines[1], seen: 2 }))
let badgeOn = false
```

lapse 샷 motions에 배지 추가 (`timelapse` 샷 push 시 motions 배열 맨 앞에):

```ts
motions: [
  { v: 'loop', text: `남은 ${inLapse.count}회 빨리감기` },
  ...(target ? [...] : [...]),  // 기존 내용 유지
],
```

이벤트 루프 본문, lapse 체크 뒤 · motions 채우기 앞:

```ts
const inLoop = loopSpans.find(l => e.seq >= l.from && e.seq <= l.to)
if (inLoop && e.kind === 'line' && e.observedAtLine === inLoop.headerLine) {
  inLoop.seen += 1
  motions.push({ v: 'loop', text: `반복 ${inLoop.seen}회차 / 총 ${inLoop.total}회` })
  badgeOn = true
} else if (!inLoop && badgeOn) {
  motions.push({ v: 'loopEnd' })
  badgeOn = false
}
```

`WorldStage.tsx` — 초기 숨김 목록에 `.film-loop` 추가, 스트립 렌더 (film-error 아래):

```tsx
<g className="film-loop">
  <rect x={24} y={14} width={240} height={30} rx={15} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1.2} />
  <text className="film-loop-text svg-value" x={40} y={34} />
</g>
```

타임라인 케이스 (raise 시 배지 숨김도 함께):

```ts
case 'loop': {
  const text = m.text
  tl.call(() => {
    const el = root.querySelector('.film-loop-text')
    if (el) el.textContent = text
  }, undefined, label)
  tl.to(q('.film-loop')!, { opacity: 1, duration: d * 0.3 }, label)
  tl.fromTo(q('.film-loop')!, { scale: 1.05 }, { scale: 1, duration: d * 0.4, transformOrigin: 'left center' }, label)
  break
}
case 'loopEnd':
  tl.to(q('.film-loop')!, { opacity: 0, duration: d * 0.4 }, label)
  break
```

`raise` 케이스 첫 줄에 추가: `tl.to(q('.film-loop')!, { opacity: 0, duration: d * 0.2 }, label)` (오류 스트립과 같은 자리 — 오류가 이긴다)

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
git add src/film
git commit -m "feat: loop badge — iteration counter and fast-forward notice on stage"
```

---

### Task 6: compare — 비교를 값·부등호·하이라이트로

**Files:**
- Modify: `src/film/types.ts`, `src/film/choreograph.ts`, `src/film/WorldStage.tsx`, `src/App.tsx`, `src/routes/Demo.tsx`
- Test: `src/film/choreograph.test.ts`

**Interfaces:**
- Consumes: 소스 코드 문자열 (신규 3번째 인자)
- Produces: `choreograph(events, plan, code?: string)`. `Motion`에

```ts
export type CompareTarget =
  | { kind: 'cell'; objectId: number; index: number }
  | { kind: 'var'; varKey: string }
// Motion에 추가
| { v: 'compare'; text: string; targets: CompareTarget[] }
```

접지 규칙: 이름→그 프레임 지역 prim, `이름[첨자]`→첨자가 리터럴/지역 int(±리터럴 오프셋 허용, `arr[j+1]`)일 때 리스트 칸 prim. 양변 접지 + 타깃 1개 이상일 때만 발화. 참/거짓은 양변 숫자일 때만.

- [ ] **Step 1: 실패하는 테스트**

```ts
describe('choreograph: compare', () => {
  const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
    seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
    causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...over,
  })
  it('if a > b 라인에서 값·부등호·판정이 나온다', () => {
    const code = 'a = 5\nb = 4\nif a > b:\n    c = 1\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ causedByLine: 1, observedAtLine: 2, localsDelta: [{ name: 'a', op: 'set', value: P('5') }] }, 1),
      ev({ causedByLine: 2, observedAtLine: 3, localsDelta: [{ name: 'b', op: 'set', value: P('4') }] }, 2),
      ev({ causedByLine: 3, observedAtLine: 4, localsDelta: [{ name: 'c', op: 'set', value: P('1') }] }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const cmp = shots.flatMap(s => s.motions).find(m => m.v === 'compare') as { text: string; targets: unknown[] }
    expect(cmp).toBeDefined()
    expect(cmp.text).toBe('5 > 4 → 참')
    expect(cmp.targets.length).toBe(2)
  })
  it('첨자 비교 arr[j] > arr[j+1]가 칸 타깃으로 접지된다', () => {
    const code = 'arr = [5, 4]\nj = 0\nif arr[j] > arr[j + 1]:\n    pass\n'
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ observedAtLine: 2, localsDelta: [{ name: 'arr', op: 'set', value: { k: 'ref', id: 1 } }],
        objectsDelta: [{ op: 'set', obj: { id: 1, type: 'list', items: [P('5'), P('4')] } }] }, 1),
      ev({ observedAtLine: 3, localsDelta: [{ name: 'j', op: 'set', value: P('0') }] }, 2),
      ev({ observedAtLine: 4 }, 3),
    ]
    const shots = choreograph(events, buildStage(events), code)
    const cmp = shots.flatMap(s => s.motions).find(m => m.v === 'compare') as
      { text: string; targets: { kind: string; index?: number }[] } | undefined
    expect(cmp).toBeDefined()
    expect(cmp!.text).toBe('5 > 4 → 참')
    expect(cmp!.targets).toEqual([
      { kind: 'cell', objectId: 1, index: 0 },
      { kind: 'cell', objectId: 1, index: 1 },
    ])
  })
  it('접지가 안 되면 침묵한다', () => {
    const code = 'if x > y:\n    pass\n'
    const events: TraceEvent[] = [ev({ kind: 'call' }, 0), ev({ observedAtLine: 1 }, 1)]
    const shots = choreograph(events, buildStage(events), code)
    expect(shots.flatMap(s => s.motions).some(m => m.v === 'compare')).toBe(false)
  })
})
```

주의: 관측 시점 규칙 — 이벤트의 델타는 "직전 라인이 일으켜 이 라인 경계에서 관측"이므로, **델타를 locals에 반영한 뒤** 그 이벤트의 `observedAtLine` 라인에서 비교를 감지한다 (조건식이 보는 상태와 일치).

- [ ] **Step 2: 실패 확인** → FAIL

- [ ] **Step 3: 구현**

`choreograph.ts` 모듈 레벨에 감지기:

```ts
const CMP_RE = /([A-Za-z_]\w*(?:\[[^\]]+\])?|-?\d+(?:\.\d+)?)\s*(<=|>=|==|!=|<|>)\s*([A-Za-z_]\w*(?:\[[^\]]+\])?|-?\d+(?:\.\d+)?)/

const stripNoise = (line: string) => line.split('#')[0].replace(/'[^']*'|"[^"]*"/g, '""')

type Operand = { text: string; num: number | null; target?: CompareTarget }

function resolveOperand(
  raw: string, frameId: number,
  locals: Map<string, Value>, objects: Map<number, ObjectSnap>,
): Operand | null {
  const s = raw.trim()
  if (/^-?\d+(\.\d+)?$/.test(s)) return { text: s, num: Number(s) }
  const m = s.match(/^([A-Za-z_]\w*)(?:\[([^\]]+)\])?$/)
  if (!m) return null
  const v = locals.get(`${frameId}:${m[1]}`)
  if (!v) return null
  if (!m[2]) {
    if (v.k !== 'prim') return null
    return {
      text: v.v,
      num: v.t === 'int' || v.t === 'float' ? Number(v.v) : null,
      target: { kind: 'var', varKey: `${frameId}:${m[1]}` },
    }
  }
  if (v.k !== 'ref') return null
  const obj = objects.get(v.id)
  if (!obj?.items) return null
  const sub = m[2].replace(/\s+/g, '').match(/^([A-Za-z_]\w*|\d+)(?:([+-])(\d+))?$/)
  if (!sub) return null
  let base: number | null = null
  if (/^\d+$/.test(sub[1])) base = Number(sub[1])
  else {
    const iv = locals.get(`${frameId}:${sub[1]}`)
    if (iv?.k === 'prim' && iv.t === 'int') base = Number(iv.v)
  }
  if (base === null) return null
  const idx = base + (sub[2] === '-' ? -Number(sub[3]) : Number(sub[3] ?? 0))
  const item = obj.items[idx]
  if (!item || item.k !== 'prim') return null
  return {
    text: item.v,
    num: item.t === 'int' || item.t === 'float' ? Number(item.v) : null,
    target: { kind: 'cell', objectId: v.id, index: idx },
  }
}

function detectCompare(
  rawLine: string, frameId: number,
  locals: Map<string, Value>, objects: Map<number, ObjectSnap>,
): Motion | null {
  const m = stripNoise(rawLine).match(CMP_RE)
  if (!m) return null
  const a = resolveOperand(m[1], frameId, locals, objects)
  const b = resolveOperand(m[3], frameId, locals, objects)
  if (!a || !b) return null
  const targets = [a.target, b.target].filter((t): t is CompareTarget => !!t)
  if (targets.length === 0) return null
  let verdict = ''
  if (a.num !== null && b.num !== null && Number.isFinite(a.num) && Number.isFinite(b.num)) {
    const op = m[2]
    const res =
      op === '<' ? a.num < b.num : op === '>' ? a.num > b.num :
      op === '<=' ? a.num <= b.num : op === '>=' ? a.num >= b.num :
      op === '==' ? a.num === b.num : a.num !== b.num
    verdict = res ? ' → 참' : ' → 거짓'
  }
  return { v: 'compare', text: `${a.text} ${m[2]} ${b.text}${verdict}`, targets }
}
```

시그니처·본문 배선:

```ts
export function choreograph(events: TraceEvent[], _plan: StagePlan, code?: string): Shot[] {
  const srcLines = (code ?? '').split('\n')
  const locals = new Map<string, Value>()
  ...
  for (const e of events) {
    // 델타 먼저 반영 — 조건식이 보는 상태
    for (const d of e.localsDelta) {
      const key = `${e.frameId}:${d.name}`
      if (d.op === 'delete') locals.delete(key)
      else if (d.value) locals.set(key, d.value)
    }
    ...objectsDelta 반영(기존)...
    ...lapse 체크(기존)...
    ...loop 배지(Task 5)...
    if (code && e.kind === 'line') {
      const cmp = detectCompare(srcLines[e.observedAtLine - 1] ?? '', e.frameId, locals, objects)
      if (cmp) motions.push(cmp)
    }
    ...이하 기존...
```

`WorldStage.tsx` — 초기 숨김에 `.film-compare` 추가, 칩 렌더:

```tsx
<g className="film-compare">
  <rect x={layout.width / 2 - 130} y={14} width={260} height={30} rx={15} fill="var(--panel)" stroke="var(--accent)" strokeWidth={1.4} />
  <text className="film-compare-text svg-name" x={layout.width / 2} y={34} textAnchor="middle" />
</g>
```

타임라인 케이스 (`raise`에도 `.film-compare` 숨김 추가):

```ts
case 'compare': {
  const text = m.text
  const targets = m.targets
  tl.call(() => {
    const el = root.querySelector('.film-compare-text')
    if (el) el.textContent = text
  }, undefined, label)
  tl.fromTo(q('.film-compare')!, { opacity: 0, y: -6 }, { opacity: 1, y: 0, duration: d * 0.3, ease: 'power2.out' }, label)
  for (const t of targets) {
    const el = q(t.kind === 'cell' ? cellSel(t.objectId, t.index) : varSel(t.varKey))
    if (el) tl.fromTo(el, { scale: 1 }, { scale: 1.14, duration: d * 0.35, yoyo: true, repeat: 1, transformOrigin: 'center' }, label)
  }
  tl.to(q('.film-compare')!, { opacity: 0, duration: d * 0.3 }, `${label}+=${d * 0.95}`)
  break
}
```

호출부: `App.tsx` `choreograph(result.events, plan, code)` / `Demo.tsx` `choreograph(demo.fixture.events, p, demo.fixture.code)`

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
git add src/film src/App.tsx src/routes/Demo.tsx
git commit -m "feat: compare motion — grounded operand values, operator, verdict, target highlights"
```

---

### Task 7: swap — 두 칸이 실제로 자리를 바꾼다

**Files:**
- Modify: `src/film/types.ts`, `src/film/choreograph.ts`, `src/film/WorldStage.tsx`
- Test: `src/film/choreograph.test.ts`

**Interfaces:**
- Produces: `Motion`에 `{ v: 'swap'; objectId: number; i: number; k: number; iText: string; kText: string }` (iText/kText = 교환 **후** 각 칸의 표시 문자열). 같은 크기에서 정확히 두 인덱스가 서로 값을 교환하면 setCell 대신 swap + slow.

- [ ] **Step 1: 실패하는 테스트**

```ts
describe('choreograph: swap', () => {
  const ev = (over: Partial<TraceEvent>, seq: number): TraceEvent => ({
    seq, kind: 'line', frameId: 0, parentFrameId: null, func: '<module>',
    causedByLine: null, observedAtLine: 1, localsDelta: [], objectsDelta: [], stdout: '', ...over,
  })
  const listSet = (items: string[]) => ({
    op: 'set' as const, obj: { id: 1, type: 'list', items: items.map(v => P(v)) },
  })
  it('전위 교환이 swap 모션이 되고 느리게 재생된다', () => {
    const events: TraceEvent[] = [
      ev({ kind: 'call' }, 0),
      ev({ localsDelta: [{ name: 'a', op: 'set', value: { k: 'ref', id: 1 } }], objectsDelta: [listSet(['5', '4', '9'])] }, 1),
      ev({ objectsDelta: [listSet(['4', '5', '9'])] }, 2),
    ]
    const shots = choreograph(events, buildStage(events))
    const hit = shots.flatMap(s => s.motions.map(m => ({ m, s }))).find(x => x.m.v === 'swap')
    expect(hit).toBeDefined()
    expect(hit!.m).toMatchObject({ objectId: 1, i: 0, k: 1, iText: '4', kText: '5' })
    expect(hit!.s.durationMs).toBeGreaterThan(520)
    expect(hit!.s.motions.some(m => m.v === 'setCell')).toBe(false)
  })
})
```

- [ ] **Step 2: 실패 확인** → FAIL

- [ ] **Step 3: 구현**

`types.ts`: `| { v: 'swap'; objectId: number; i: number; k: number; iText: string; kText: string }`

`choreograph.ts` Task 4의 "같은 크기" 분기를 교체:

```ts
} else if (size === prev.length && size > 0) {
  const changed: number[] = []
  for (let i = 0; i < size; i++) if (texts[i] !== prev[i]) changed.push(i)
  if (
    changed.length === 2 &&
    texts[changed[0]] === prev[changed[1]] &&
    texts[changed[1]] === prev[changed[0]]
  ) {
    motions.push({ v: 'swap', objectId: d.obj.id, i: changed[0], k: changed[1], iText: texts[changed[0]], kText: texts[changed[1]] })
    slow = true
  } else {
    for (const i of changed) motions.push({ v: 'setCell', objectId: d.obj.id, index: i, text: texts[i] })
  }
}
```

`WorldStage.tsx` 타임라인 케이스 — 두 칸이 서로의 자리로 이동한 뒤, 보이지 않는 순간에 텍스트를 최종 배치로 바꾸고 transform을 ري셋한다:

```ts
case 'swap': {
  const a = q(cellSel(m.objectId, m.i))
  const b = q(cellSel(m.objectId, m.k))
  if (!a || !b) break
  const dx = (m.k - m.i) * layout.cellW
  const id = m.objectId
  const i = m.i
  const k = m.k
  const iText = m.iText
  const kText = m.kText
  tl.to(a, { x: dx, scale: 1.12, duration: d * 0.55, ease: 'power2.inOut', transformOrigin: 'center' }, label)
  tl.to(b, { x: -dx, scale: 1.12, duration: d * 0.55, ease: 'power2.inOut', transformOrigin: 'center' }, label)
  tl.call(() => {
    const ta = root.querySelector(`${cellSel(id, i)} .film-cell-text`)
    const tb = root.querySelector(`${cellSel(id, k)} .film-cell-text`)
    if (ta) ta.textContent = iText
    if (tb) tb.textContent = kText
  }, undefined, `${label}+=${d * 0.55}`)
  tl.set([a, b], { x: 0 }, `${label}+=${d * 0.55}`)
  tl.to([a, b], { scale: 1, duration: d * 0.3, ease: 'back.out(2)' }, `${label}+=${d * 0.58}`)
  break
}
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
git add src/film
git commit -m "feat: swap motion — transposed cells physically trade places"
```

---

### Task 8: AI 연출 비차단 + 지연 최적화

**Files:**
- Modify: `src/director/gemini.ts`, `src/director/llmDirector.ts`, `src/App.tsx`

**Interfaces:**
- Produces: `makeGeminiCall` — `thinkingConfig: { thinkingBudget: 0 }` + 20초 AbortController. 프롬프트 스팬 슬림화(eventKinds/funcs/sourceSeqRange 제거, stdout 80자, "배열 순서 = 실행 순서" 명시). App — 규칙 영상 즉시 재생, AI는 백그라운드(`runIdRef` 토큰), 도착 시 screenplay/steps 교체. `aiPending` 태그 "AI 연출 준비 중…". 로딩 단계에서 'directing' 제거.

- [ ] **Step 1: gemini.ts 수정**

```ts
export function makeGeminiCall(apiKey: string, model = 'gemini-2.5-flash'): LlmCallFn {
  return async (prompt: string) => {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 20000)
    try {
      const res = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-goog-api-key': apiKey },
          signal: ctrl.signal,
          body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: {
              responseMimeType: 'application/json',
              temperature: 0.4,
              // 연출 선택은 구조화 출력 과제 — thinking이 지연만 키운다
              thinkingConfig: { thinkingBudget: 0 },
            },
          }),
        },
      )
      if (!res.ok) throw new Error(`Gemini API ${res.status}: ${(await res.text()).slice(0, 200)}`)
      const data = await res.json()
      const text = data?.candidates?.[0]?.content?.parts?.[0]?.text
      if (typeof text !== 'string') throw new Error('Gemini 응답에 텍스트가 없습니다')
      return text
    } finally {
      clearTimeout(timer)
    }
  }
}
```

- [ ] **Step 2: 프롬프트 슬림화** (`llmDirector.ts`)

```ts
// LLM에 필요한 필드만 — 순서는 배열 순서가 전달한다
const promptSpans = (digest: Digest) =>
  digest.spans.map(s => ({
    spanId: s.spanId,
    lines: s.lines,
    changedVars: s.changedVars,
    ...(s.iterations ? { iterations: s.iterations } : {}),
    ...(s.stdoutDelta ? { stdout: s.stdoutDelta.slice(0, 80) } : {}),
    ...(s.exception ? { exception: s.exception } : {}),
  }))
```

buildPrompt에서 `${JSON.stringify(digest.spans)}` → `${JSON.stringify(promptSpans(digest))}`, 스팬 소개 문장에 "스팬 배열은 실행 순서 그대로 나열되어 있다" 추가, 규칙 1을 "spanRef는 위 Digest에 있는 spanId만. **배열 순서(=실행 순서)**대로만 배열."로 수정.

- [ ] **Step 3: App 비차단 배선**

`LoadingStage`에서 `'directing'` 제거(타입·라벨). 상태 추가:

```ts
const [aiPending, setAiPending] = useState(false)
const runIdRef = useRef(0)
const indexRef = useRef(0)
indexRef.current = index
const playingRef = useRef(false)
playingRef.current = playing
const restoreRef = useRef<{ index: number; playing: boolean } | null>(null)
```

`executeRun` 재작성 (AI가 재생을 막지 않는다):

```ts
const executeRun = async () => {
  if (loading !== null || !code.trim()) return
  const found = preflight(code)
  setIssues(found)
  if (found.some(i => i.level === 'block')) return

  const runId = ++runIdRef.current
  setLoading('python-loading')
  setRun(null)
  setAiPending(false)
  try {
    const result = await runTrace(code, s => setLoading(s), {
      maxEvents: settings.maxEvents,
      timeoutMs: settings.timeoutMs,
    })
    if (runId !== runIdRef.current) return
    const snaps = buildSnapshots(result.events)
    const screenplay = buildScreenplay(result.events)
    const plan = buildStage(result.events)
    const layout = layoutStage(plan)
    const filmShots = choreograph(result.events, plan, code)
    setRun({
      steps: expandScreenplay(screenplay, snaps), snaps, screenplay,
      clipped: result.clipped, error: result.error, directorMode: 'rule',
      plan, layout, shots: filmShots,
    })
    setLoading(null)
    if (filmShots.length > 0 && settings.autoplay) setTimeout(play, 120)

    // AI 연출은 배경에서 — 도착하면 자막·챕터·완급만 좋아지고, 실패해도 영화는 이미 완성돼 있다
    if (settings.aiDirector && geminiApiKey && result.events.length > 0) {
      setAiPending(true)
      void (async () => {
        try {
          const ai = await generateScreenplayWithSalvage(code, buildDigest(result.events), makeGeminiCall(geminiApiKey), screenplay)
          if (runId !== runIdRef.current) return
          setRun(prev => {
            if (!prev) return prev
            restoreRef.current = { index: indexRef.current, playing: playingRef.current }
            return {
              ...prev,
              screenplay: ai.screenplay,
              steps: expandScreenplay(ai.screenplay, snaps),
              directorMode: ai.mode,
            }
          })
        } catch {
          if (runId === runIdRef.current) setRun(prev => (prev ? { ...prev, directorMode: 'ai-fallback' } : prev))
        } finally {
          if (runId === runIdRef.current) setAiPending(false)
        }
      })()
    }
  } catch (err) {
    if (runId !== runIdRef.current) return
    setLoading(null)
    setRun({
      steps: [], snaps: [], screenplay: { chapters: [] }, clipped: false, error: String(err), directorMode: 'rule',
      plan: EMPTY_PLAN, layout: layoutStage(EMPTY_PLAN), shots: [],
    })
  }
}
```

(Task 10에서 `shots: decorateShots(...)` 교체와 위치 복원 effect가 이 블록에 합류한다 — 이 태스크에서는 steps/screenplay 교체까지만.)

DirectorMode에 `'ai-partial'` 추가, 라벨:

```ts
const directorLabel =
  run?.directorMode === 'ai' ? 'AI 연출'
  : run?.directorMode === 'ai-partial' ? 'AI 연출·일부 보강'
  : run?.directorMode === 'ai-fallback' ? '규칙 폴백' : '규칙 연출'
```

상태 태그에 대기 표시:

```tsx
{aiPending && <span className="tl-tag">AI 연출 준비 중…</span>}
{run && !aiPending && (
  <span className={`tl-tag ${run.directorMode === 'ai' || run.directorMode === 'ai-partial' ? 'tl-tag--info' : ''}`}>{directorLabel}</span>
)}
```

이 태스크 시점에는 `generateScreenplayWithSalvage`가 아직 없다 — Task 9와 **같은 커밋**으로 묶거나, 임시로 기존 `generateScreenplay`를 호출하고 Task 9에서 교체한다. (계획상 Task 8·9를 연달아 구현하고 함께 검증 후 각각 커밋해도 된다 — tsc가 기준.)

- [ ] **Step 4: 검증** — `npx tsc -b && npx vitest run` (Task 9 완료 후), 키가 있으면 `npx vitest run src/bench/llmPass.bench.test.ts`로 thinkingBudget 0의 대본 검증 통과율 확인 (6/6 기대). 키가 없으면 "미검증 — 수동 확인 필요"를 커밋 메시지에 남긴다.

```bash
git add src/director/gemini.ts src/director/llmDirector.ts src/App.tsx
git commit -m "perf: non-blocking AI direction — instant rule film, zero thinking budget, slim prompt, 20s timeout"
```

---

### Task 9: salvage — 장면 단위 부분 수용 + 규칙 충전

**Files:**
- Modify: `src/director/resolver.ts`, `src/director/llmDirector.ts`
- Test: `src/director/resolver.test.ts`

**Interfaces:**
- Produces:
  - `resolver.ts`: `export function salvageScreenplay(raw: unknown, digest: Digest, rule: Screenplay): Screenplay | null` — 유효 장면만 채택(순서 위반·무효 spanRef·바인딩 불일치 장면은 개별 폐기), 채택 0이면 null, 빠진 구간은 규칙 장면으로 충전, AI 챕터 제목 유지.
  - `llmDirector.ts`: `export type DirectedResult = { screenplay: Screenplay; mode: 'ai' | 'ai-partial' }`, `export async function generateScreenplayWithSalvage(code, digest, call, rule): Promise<DirectedResult>` — 엄격 2회 시도(기존) → 실패 시 마지막 응답 salvage → 그것도 없으면 throw(호출부 폴백). 기존 `generateScreenplay`는 벤치 호환을 위해 유지.

- [ ] **Step 1: 실패하는 테스트** (`resolver.test.ts`에 추가)

```ts
import { salvageScreenplay } from './resolver'
import type { Screenplay } from '../screenplay/types'

describe('salvageScreenplay', () => {
  const digest: Digest = {
    spans: [
      { spanId: 's0', sourceSeqRange: [0, 0], lines: [1, 1], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['a'] },
      { spanId: 's1', sourceSeqRange: [1, 1], lines: [2, 2], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['b'] },
      { spanId: 's2', sourceSeqRange: [2, 2], lines: [3, 3], eventKinds: ['line'], funcs: ['<module>'], changedVars: ['c'] },
    ],
  }
  const ruleScene = (seq: number, name: string) => ({
    seqStart: seq, seqEnd: seq, primitive: 'variables' as const, focus: [name],
    pacing: 'normal' as const, narration: { template: `${name} 변경`, bindings: {} },
  })
  const rule: Screenplay = { chapters: [{ title: '실행', scenes: [ruleScene(0, 'a'), ruleScene(1, 'b'), ruleScene(2, 'c')] }] }
  const aiScene = (ref: string) => ({
    spanRef: ref, primitive: 'variables', focus: [], pacing: 'slow',
    narration: { template: 'AI 장면', bindings: {} },
  })

  it('무효 장면만 버리고 빠진 구간을 규칙 장면으로 메꾼다', () => {
    const raw = { chapters: [{ title: '1장', scenes: [aiScene('s0'), aiScene('없는거'), aiScene('s2')] }] }
    const out = salvageScreenplay(raw, digest, rule)!
    expect(out).not.toBeNull()
    const flat = out.chapters.flatMap(c => c.scenes)
    expect(flat.map(s => s.seqStart)).toEqual([0, 1, 2])
    expect(flat[1].narration.template).toBe('b 변경')      // 규칙 충전
    expect(flat[0].narration.template).toBe('AI 장면')     // AI 채택
    expect(out.chapters[0].title).toBe('1장')
  })
  it('순서를 어긴 장면은 그 장면만 버린다', () => {
    const raw = { chapters: [{ title: '1장', scenes: [aiScene('s2'), aiScene('s0'), aiScene('s1')] }] }
    const out = salvageScreenplay(raw, digest, rule)!
    const flat = out.chapters.flatMap(c => c.scenes)
    // s2 채택 → s0·s1은 순서 위반으로 폐기 → 규칙으로 충전
    expect(flat.map(s => s.seqStart)).toEqual([0, 1, 2])
    expect(flat[2].narration.template).toBe('AI 장면')
  })
  it('전부 무효면 null (전체 규칙 폴백)', () => {
    const raw = { chapters: [{ title: '1장', scenes: [aiScene('x'), aiScene('y')] }] }
    expect(salvageScreenplay(raw, digest, rule)).toBeNull()
  })
})
```

- [ ] **Step 2: 실패 확인** → FAIL (salvageScreenplay 없음)

- [ ] **Step 3: 구현**

`resolver.ts` — 장면 하나 검증을 함수로 추출해 strict/salvage가 공유:

```ts
function resolveScene(
  sc: RawScene, byId: Map<string, DigestSpan>, lastEnd: number, where: string,
): { scene: Scene; end: number } {
  if (typeof sc.spanRef !== 'string' || !byId.has(sc.spanRef))
    throw new ValidationError(`${where}: 존재하지 않는 spanRef (${String(sc.spanRef)})`)
  const span = byId.get(sc.spanRef)!
  if (span.sourceSeqRange[0] <= lastEnd)
    throw new ValidationError(`${where}: 실행 순서를 어기는 배열 (spanRef ${sc.spanRef})`)
  if (typeof sc.primitive !== 'string' || !PRIMITIVES.includes(sc.primitive as PrimitiveKind))
    throw new ValidationError(`${where}: 허용되지 않은 primitive (${String(sc.primitive)})`)
  const pacing: Pacing = PACINGS.includes(sc.pacing as Pacing) ? (sc.pacing as Pacing) : 'normal'
  const template = typeof sc.narration?.template === 'string' ? sc.narration.template : ''
  if (!template) throw new ValidationError(`${where}: narration.template이 필요합니다`)
  const bindings: Scene['narration']['bindings'] = {}
  for (const [key, b] of Object.entries(sc.narration?.bindings ?? {})) {
    if (typeof b?.name !== 'string') throw new ValidationError(`${where}: 바인딩 ${key}에 name이 필요합니다`)
    bindings[key] = { seq: span.sourceSeqRange[1], name: b.name }
  }
  for (const t of template.matchAll(/\{(\w+)\}/g)) {
    if (!bindings[t[1]]) throw new ValidationError(`${where}: {${t[1]}}에 대한 바인딩이 없습니다`)
  }
  const focus = Array.isArray(sc.focus) ? sc.focus.filter((f): f is string => typeof f === 'string') : []
  return {
    scene: {
      seqStart: span.sourceSeqRange[0], seqEnd: span.sourceSeqRange[1],
      primitive: sc.primitive as PrimitiveKind, focus, pacing,
      ...(span.iterations && span.iterations > 1 ? { repeat: span.iterations } : {}),
      narration: { template, bindings },
    },
    end: span.sourceSeqRange[1],
  }
}
```

`resolveScreenplay`는 이 함수를 사용하도록 축약(동작 동일 — 기존 테스트가 회귀를 잡는다). salvage:

```ts
// AI가 실수해도 유효한 장면은 살린다 — 빠진 구간은 규칙 장면으로 메꿔 완주 보장
export function salvageScreenplay(raw: unknown, digest: Digest, rule: Screenplay): Screenplay | null {
  const doc = raw as RawScreenplay
  if (!doc || !Array.isArray(doc.chapters)) return null
  const byId = new Map<string, DigestSpan>(digest.spans.map(s => [s.spanId, s]))
  let lastEnd = -1
  const kept: { scene: Scene; ch: number }[] = []
  const titles: string[] = []
  doc.chapters.forEach((ch, ci) => {
    titles.push(typeof ch.title === 'string' && ch.title ? ch.title : `구간 ${ci + 1}`)
    for (const sc of Array.isArray(ch.scenes) ? ch.scenes : []) {
      try {
        const r = resolveScene(sc, byId, lastEnd, `챕터 ${ci}`)
        kept.push({ scene: r.scene, ch: ci })
        lastEnd = r.end
      } catch {
        /* 이 장면만 버린다 */
      }
    }
  })
  if (kept.length === 0) return null

  const covered = (seq: number) => kept.some(k => seq >= k.scene.seqStart && seq <= k.scene.seqEnd)
  const fillers = rule.chapters.flatMap(c => c.scenes).filter(s => !covered(s.seqStart))
  const merged = [...kept, ...fillers.map(scene => ({ scene, ch: -1 }))]
    .sort((a, b) => a.scene.seqStart - b.scene.seqStart)

  const chapters: Chapter[] = titles.map(title => ({ title, scenes: [] as Scene[] }))
  let cur = 0
  for (const m of merged) {
    if (m.ch >= 0) cur = m.ch
    chapters[cur].scenes.push(m.scene)
  }
  return { chapters: chapters.filter(c => c.scenes.length > 0) }
}
```

(`Chapter` 타입 import 추가.)

`llmDirector.ts`:

```ts
export type DirectedResult = { screenplay: Screenplay; mode: 'ai' | 'ai-partial' }

export async function generateScreenplayWithSalvage(
  code: string, digest: Digest, call: LlmCallFn, rule: Screenplay,
): Promise<DirectedResult> {
  const prompt = buildPrompt(code, digest)
  let lastError = ''
  let lastText = ''
  for (let attempt = 0; attempt < 2; attempt++) {
    const ask = attempt === 0 ? prompt : `${prompt}\n\n## 이전 시도 오류 (수정해서 다시)\n${lastError}`
    const text = await call(ask)
    lastText = text
    try {
      return { screenplay: resolveScreenplay(JSON.parse(stripFences(text)), digest), mode: 'ai' }
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err)
    }
  }
  try {
    const salvaged = salvageScreenplay(JSON.parse(stripFences(lastText)), digest, rule)
    if (salvaged) return { screenplay: salvaged, mode: 'ai-partial' }
  } catch {
    /* JSON 자체가 깨짐 — 아래 throw로 규칙 폴백 */
  }
  throw new Error(`대본 생성 실패: ${lastError}`)
}
```

App의 백그라운드 호출을 `generateScreenplayWithSalvage(...)`로 확정 (Task 8 참고).

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
git add src/director src/App.tsx
git commit -m "feat: scene-level salvage — keep valid AI scenes, fill gaps with rule scenes"
```

---

### Task 10: decorate — AI가 잘하면 디테일이 산다

**Files:**
- Create: `src/film/decorate.ts`
- Modify: `src/film/types.ts`, `src/film/WorldStage.tsx`, `src/App.tsx`
- Test: `src/film/decorate.test.ts`

**Interfaces:**
- Consumes: `Shot[]`, `Screenplay`, `StagePlan`
- Produces: `export function decorateShots(shots: Shot[], screenplay: Screenplay, plan: StagePlan): Shot[]` — 샷 수 보존(1:1). scene.pacing → durationMs ×(slow 1.5 / fast 0.6), 220~1800ms 클램프, timelapse 샷 제외. slow 장면 + focus 접지 시 `{ v: 'spotlight'; varKeys: string[] }` 모션 추가. App은 AI 도착 시에만 적용(`ai`/`ai-partial`), 재생 위치 복원.

- [ ] **Step 1: 실패하는 테스트** (`src/film/decorate.test.ts`)

```ts
import { describe, it, expect } from 'vitest'
import { decorateShots } from './decorate'
import type { Shot, StagePlan } from './types'
import type { Screenplay } from '../screenplay/types'

const plan: StagePlan = {
  objects: [], frames: [], slotCount: 0, maxStackDepth: 0, maxListLength: 0, leadObjectId: null,
  variables: [{ varKey: '0:a', frameId: 0, name: 'a', life: { from: 0, to: 9 }, holdsRef: false }],
}
const shot = (seq: number, over: Partial<Shot> = {}): Shot => ({
  seq, motions: [{ v: 'enterVar', varKey: '0:a' }], durationMs: 520, focus: null, ...over,
})
const play = (pacing: 'slow' | 'fast' | 'normal', focus: string[] = []): Screenplay => ({
  chapters: [{ title: 'c', scenes: [{ seqStart: 0, seqEnd: 5, primitive: 'variables', focus, pacing, narration: { template: '', bindings: {} } }] }],
})

describe('decorateShots', () => {
  it('slow 장면은 느려지고 spotlight가 붙는다', () => {
    const out = decorateShots([shot(1)], play('slow', ['a']), plan)
    expect(out[0].durationMs).toBe(780)
    expect(out[0].motions.at(-1)).toEqual({ v: 'spotlight', varKeys: ['0:a'] })
  })
  it('fast 장면은 빨라진다 (클램프 하한 220)', () => {
    expect(decorateShots([shot(1)], play('fast'), plan)[0].durationMs).toBe(312)
    const tiny = decorateShots([shot(1, { durationMs: 300 })], play('fast'), plan)
    expect(tiny[0].durationMs).toBe(220)
  })
  it('장면 밖 샷·timelapse 샷은 건드리지 않는다', () => {
    expect(decorateShots([shot(9)], play('slow'), plan)[0].durationMs).toBe(520)
    const lapse = decorateShots([shot(1, { timelapse: 5 })], play('slow'), plan)
    expect(lapse[0].durationMs).toBe(520)
  })
  it('샷 수를 보존한다', () => {
    expect(decorateShots([shot(1), shot(2)], play('slow'), plan).length).toBe(2)
  })
})
```

- [ ] **Step 2: 실패 확인** → FAIL

- [ ] **Step 3: 구현**

`types.ts`: `| { v: 'spotlight'; varKeys: string[] }`

`src/film/decorate.ts`:

```ts
import type { Pacing, Screenplay } from '../screenplay/types'
import type { Shot, StagePlan } from './types'

const FACTOR: Record<Pacing, number> = { slow: 1.5, normal: 1, fast: 0.6 }

// AI 대본은 완급과 시선만 보탠다 — 모션 종류·값·좌표는 규칙 콘티의 것 그대로.
// AI가 없거나 실패하면 이 함수가 안 불릴 뿐, 영화는 이미 완성돼 있다.
export function decorateShots(shots: Shot[], screenplay: Screenplay, plan: StagePlan): Shot[] {
  const scenes = screenplay.chapters.flatMap(c => c.scenes)
  return shots.map(sh => {
    if (sh.timelapse) return sh
    const sc = scenes.find(s => sh.seq >= s.seqStart && sh.seq <= s.seqEnd)
    if (!sc) return sh
    const durationMs = Math.min(1800, Math.max(220, Math.round(sh.durationMs * FACTOR[sc.pacing])))
    let motions = sh.motions
    if (sc.pacing === 'slow' && sc.focus.length > 0) {
      const varKeys = sc.focus
        .map(name => plan.variables.find(v => v.name === name && v.life.from <= sh.seq && sh.seq <= v.life.to))
        .filter(v => v !== undefined)
        .map(v => v.varKey)
      if (varKeys.length > 0) motions = [...sh.motions, { v: 'spotlight', varKeys }]
    }
    return { ...sh, durationMs, motions }
  })
}
```

`WorldStage.tsx` 케이스:

```ts
case 'spotlight':
  for (const key of m.varKeys) {
    const el = q(varSel(key))
    if (el) tl.fromTo(el, { scale: 1 }, { scale: 1.08, duration: d * 0.4, yoyo: true, repeat: 1, transformOrigin: 'center' }, label)
  }
  break
```

`App.tsx` — Task 8의 AI 도착 setRun에 shots 교체 추가:

```ts
return {
  ...prev,
  screenplay: ai.screenplay,
  steps: expandScreenplay(ai.screenplay, snaps),
  shots: decorateShots(prev.shots, ai.screenplay, prev.plan),
  directorMode: ai.mode,
}
```

위치 복원 effect (shots 교체 → WorldStage가 타임라인 재구축 → 자식 effect가 먼저 register하므로 seek 가능):

```ts
useEffect(() => {
  const restore = restoreRef.current
  if (!restore || !run) return
  restoreRef.current = null
  if (restore.index > 0 || restore.playing) {
    seek(restore.index)
    if (restore.playing) play()
  }
}, [run, seek, play])
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
git add src/film src/App.tsx
git commit -m "feat: AI detail layer — pacing and spotlight decorate the rule film, position preserved"
```

---

### Task 11: 도움말 갱신 + 브라우저 E2E 검증

**Files:**
- Modify: `src/routes/Help.tsx`

- [ ] **Step 1: 도움말 문구 — 새 어휘를 약속으로**

VERDICTS[0].rows에서 두 행 교체:

```ts
['조건문·반복문', 'if / for / while', '비교는 실제 값과 부등호로, 반복은 회차 배지와 빨리감기로 표시'],
['리스트·dict·set 조작', 'arr.append(3)', '번호 붙은 칸이 자라고, 자리 교환은 두 칸이 실제로 움직임'],
```

CONTROLS에 추가:

```ts
['확대·축소', '무대 위에서 휠로 확대·축소하고, 확대 상태에서 드래그로 이동합니다. 우하단 버튼으로도 조절합니다.'],
```

- [ ] **Step 2: 타입·테스트 최종 확인**

Run: `npx tsc -b && npx vitest run`
Expected: 기존 135 + 신규(raise 1, diff 2, loop 3, compare 3, swap 1, salvage 3, decorate 4 = 17) ≈ 152 passed

- [ ] **Step 3: 브라우저 검증** (dev 서버, `/app`)

| 시나리오 | 기대 |
|---|---|
| 버블 정렬 코드 실행 (`nums = [5, 4, 10, 9, 18, 1]` + 이중 for + 인접 비교·교환) | 칸 번호, "반복 N회차" 배지, "5 > 4 → 참" 칩 + 두 칸 하이라이트, 두 칸이 실제로 자리 교환 |
| `arr = [1, 2]` `print(arr[5])` | 터지는 지점까지 재생 후 상단 오류 스트립에 IndexError, 프레임 shake |
| `def f(:` (구문 오류) | 무대에 "실행이 여기서 멈췄습니다" + 오류 전문 (빈 화면 아님) |
| Ctrl+Enter | 에디터 안에서 실행 시작 |
| 휠·버튼 줌, 드래그 팬, 맞춤 | 동작, 새 실행 시 리셋 |
| AI 키 있으면 | 규칙 영상이 즉시 재생 → 태그 "AI 연출 준비 중…" → 도착 시 자막·완급 교체, 위치 유지 |

- [ ] **Step 4: Commit**

```bash
git add src/routes/Help.tsx
git commit -m "docs: help matrix promises the new visual vocabulary"
```

---

## Self-Review 결과

- **Spec coverage**: 피드백 1(Task 2)·2(Task 1)·3(Task 9·10 + 기존 구조)·4(Task 8)·5(Task 3)·6(품질 기준 — Task 4~7의 판정 근거)·7(Task 4·5·6·7)·8(Task 4·6·7 조합으로 스토리보드 성립)·9(전체)·10(Task 8~10이 기존 spanRef 계약 위에서 확장). 누락 없음.
- **Placeholder scan**: 통과 — 모든 스텝에 실제 코드·명령·기대 결과. Task 8 Step 3의 `generateScreenplayWithSalvage` 선참조는 본문에 명시(8·9 연속 구현 후 검증).
- **Type consistency**: `CompareTarget`(Task 6) ↔ WorldStage compare 케이스, `swap {i,k,iText,kText}`(Task 7) 감지·렌더 일치, `DirectedResult.mode` ↔ `DirectorMode 'ai-partial'`(Task 8·9), `spotlight.varKeys`(Task 10) ↔ WorldStage 케이스, `choreograph(events, plan, code?)` 시그니처가 App·Demo·테스트에서 동일.
