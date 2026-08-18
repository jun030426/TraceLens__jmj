# 연출 동사 (Directing Verbs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI 대본이 자막·완급을 넘어 실제 연출 지시(확대·여운·생략)를 넘기고, 백엔드가 그것을 검증·실행한다 — "AI가 대본(가이드)을 만들면 우리가 실행한다".

**Architecture:** Scene 스키마에 선택 필드 `direction: ('zoom'|'hold'|'skip')[]`을 추가한다. **동사는 대상 없는 문자열이다** — zoom의 대상은 AI가 아니라 엔진이 안다(그 구간 샷의 compare 타깃·focus 객체·프레임). 그래서 AI는 "어디를 크게 다룰지"만 고르고, 좌표·대상 해석·효과 제작은 전부 결정적 코드다. decorateShots가 동사를 카메라 모션·지속시간으로 번역하고, WorldStage의 자동 카메라 그룹(`.film-cam-auto`)이 타임라인 위에서 움직인다(수동 카메라와 중첩 합성). 남발은 결정적 캡(zoom ≤ 3, hold ≤ 2)으로 막는다.

**Tech Stack:** TypeScript, GSAP(SVG transform), vitest. 기존 spanRef 계약·폴백 사다리 변경 없음 — direction은 전 구간에서 선택 사항이며, 이상한 동사는 그 동사만 버린다.

## Global Constraints

- AI 동사는 전부 "트레이스에 이미 있는 사실의 증폭"이다 — 대상·좌표·값을 AI가 지정하지 않는다
- 알 수 없는 동사·남발은 조용히 잘라낸다 (장면은 살린다) — 실패 사다리 불변
- 색·타이포 토큰 규칙, 한국어 UI, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 유지
- 기존 테스트 159개 통과 유지. 각 태스크 후 `npx tsc -b && npx vitest run`

## 동사 의미론

| 동사 | 뜻 | 실행 | 정합성 |
|---|---|---|---|
| `zoom` | 이 구간의 사건을 확대해 보라 | 구간 첫 유효 샷에서 카메라가 대상 rect로 push-in, 구간 마지막 샷에서 복귀. 대상 우선순위: compare의 cell 타깃 객체 → focus 객체 → focus 프레임 | 대상 rect가 없으면 무시. 전역 3회 캡 |
| `hold` | 구간 끝에서 여운을 남겨라 | 구간 마지막 샷 duration ×1.9 (≤3000ms) | 전역 2회 캡 |
| `skip` | 준비 구간이니 빨리 지나가라 | 구간 전체 duration ×0.3 (≥150ms), 같은 장면의 zoom·hold 무시 | timelapse 샷은 제외 |

---

### Task 1: 스키마 + 리졸버 — direction 필드

**Files:**
- Modify: `src/screenplay/types.ts`, `src/director/resolver.ts`
- Test: `src/director/resolver.test.ts`

**Interfaces:**
- Produces: `export type DirectingVerb = 'zoom' | 'hold' | 'skip'` (screenplay/types), `Scene.direction: DirectingVerb[]` (필수 필드, 기본 `[]` — 규칙 대본은 빈 배열), resolveScene이 `sc.direction`을 화이트리스트 필터+중복 제거로 파싱 (배열 아니면 `[]`, 모르는 동사는 그 동사만 폐기)

- [ ] **Step 1: 실패하는 테스트** (resolver.test.ts에 추가)

```ts
describe('direction 파싱', () => {
  const scene = (direction: unknown) => ({
    chapters: [{ title: 't', scenes: [{ spanRef: 's0', primitive: 'variables', direction, narration: { template: '한 장면' } }] }],
  })
  it('유효 동사만 남기고 중복·미지 동사는 버린다', () => {
    const sp = resolveScreenplay(scene(['zoom', 'explode', 'zoom', 'hold']), digest)
    expect(sp.chapters[0].scenes[0].direction).toEqual(['zoom', 'hold'])
  })
  it('direction이 없거나 배열이 아니면 빈 배열', () => {
    expect(resolveScreenplay(scene(undefined), digest).chapters[0].scenes[0].direction).toEqual([])
    expect(resolveScreenplay(scene('zoom'), digest).chapters[0].scenes[0].direction).toEqual([])
  })
})
```

(기존 salvage·ruleDirector 경로는 Scene 생성 시 `direction: []`을 채운다 — 컴파일러가 알려주는 모든 Scene 리터럴에 추가.)

- [ ] **Step 2: 실패 확인** → FAIL (direction 필드 없음)
- [ ] **Step 3: 구현** — types에 DirectingVerb·Scene.direction 추가, resolveScene에서:

```ts
const VERBS: DirectingVerb[] = ['zoom', 'hold', 'skip']
const direction = Array.isArray(sc.direction)
  ? [...new Set(sc.direction.filter((v): v is DirectingVerb => VERBS.includes(v as DirectingVerb)))]
  : []
```

ruleDirector의 sceneFor·folding, expand.test의 합성 장면 등 Scene 리터럴 전부에 `direction: []` 추가.

- [ ] **Step 4: 통과 확인 + 커밋** — `feat: directing verbs in the scene contract — whitelist-filtered, targetless`

---

### Task 2: 프롬프트 확장

**Files:**
- Modify: `src/director/llmDirector.ts`

출력 형식에 `"direction":["zoom"]` 추가, 연출 규칙에:

```
10. direction(선택): 그 장면의 연출 지시. "zoom"=이 구간의 사건(비교·교환·별칭·예외)을 확대해서 보여줄 가치가 있을 때, "hold"=구간 끝에서 여운(예외·최종 결과), "skip"=단순 준비 구간 빨리감기. 정말 중요한 곳에만: zoom은 최대 3곳, hold는 최대 2곳. 확대할 대상은 시스템이 알고 있으므로 동사만 적는다.
```

- [ ] **Step 1: 프롬프트 수정** (형식 줄 + 규칙 10)
- [ ] **Step 2: `npx tsc -b && npx vitest run` 통과 + 커밋** — `feat: prompt asks for directing verbs, sparingly`

---

### Task 3: decorate — 동사 → 카메라·지속시간 번역

**Files:**
- Modify: `src/film/types.ts`, `src/film/decorate.ts`, `src/App.tsx`
- Test: `src/film/decorate.test.ts`

**Interfaces:**
- Produces: `Motion`에 `{ v: 'camera'; k: number; x: number; y: number }` (k=1,x=0,y=0이 복귀). `decorateShots(shots, screenplay, plan, layout)` — layout 인자 추가 (App 호출부 갱신).
- zoom rect 계산: 대상 rect r에 대해 `k = clamp(min(W/(r.w+120), H/(r.h+120)), 1.15, 2.1)`, `x = W/2 − k·(r.x+r.w/2)`, `y = H/2 − k·(r.y+r.h/2)`
- 전역 캡: zoom 3, hold 2 (문서 순서대로 선착순). skip이 있는 장면에서는 zoom·hold 무시.

- [ ] **Step 1: 실패하는 테스트** (decorate.test.ts에 추가 — 기존 헬퍼에 layout 목 추가)

```ts
const layoutMock: StageLayout = {
  width: 1200, height: 640, cellW: 40,
  objPos: new Map([[1, { x: 560, y: 70, w: 300, h: 64 }]]),
  varPos: new Map([['0:a', { x: 340, y: 70, w: 190, h: 36 }]]),
  framePos: new Map([[0, { x: 24, y: 500, w: 260, h: 58 }]]),
}
const playD = (direction: DirectingVerb[], pacing: Pacing = 'normal'): Screenplay => ({
  chapters: [{ title: 'c', scenes: [{ seqStart: 0, seqEnd: 5, primitive: 'variables', focus: [], pacing, direction, narration: { template: '', bindings: {} } }] }],
})

it('zoom: 대상 있는 첫 샷에 camera(k>1), 장면 마지막 샷에 복귀(k=1)가 붙는다', () => {
  const shots = [
    shot(1, { focus: { kind: 'object', objectId: 1 } }),
    shot(2),
  ]
  const out = decorateShots(shots, playD(['zoom']), plan, layoutMock)
  const cam0 = out[0].motions.find(m => m.v === 'camera') as { k: number }
  expect(cam0.k).toBeGreaterThan(1)
  const cam1 = out[1].motions.find(m => m.v === 'camera') as { k: number }
  expect(cam1.k).toBe(1)
})
it('zoom: 대상 rect가 없으면 무시된다', () => {
  const out = decorateShots([shot(1)], playD(['zoom']), plan, layoutMock) // focus null
  expect(out[0].motions.some(m => m.v === 'camera')).toBe(false)
})
it('hold: 장면 마지막 샷이 길어진다 (×1.9, ≤3000)', () => {
  const out = decorateShots([shot(1), shot(2)], playD(['hold']), plan, layoutMock)
  expect(out[1].durationMs).toBe(988)  // 520×1.9
  expect(out[0].durationMs).toBe(520)
})
it('skip: 전 샷 ×0.3(≥150), zoom·hold는 무시', () => {
  const out = decorateShots([shot(1, { focus: { kind: 'object', objectId: 1 } })], playD(['skip', 'zoom', 'hold']), plan, layoutMock)
  expect(out[0].durationMs).toBe(156)
  expect(out[0].motions.some(m => m.v === 'camera')).toBe(false)
})
it('전역 캡: zoom 4장면 → 앞의 3장면만', () => { /* 4개 장면 스크린플레이로 camera 등장 장면 수 == 3 확인 */ })
```

- [ ] **Step 2: 실패 확인** → FAIL
- [ ] **Step 3: 구현** — decorate에 장면별 verbs 처리(skip 우선), zoomRectOf(scene, shots, layout): 장면 내 샷 순회하며 compare cell 타깃 객체 → focus object → focus frame 순으로 rect 탐색. camera 모션 push. pacing·spotlight 기존 로직 유지.
- [ ] **Step 4: 통과 + 커밋** — `feat: decorate translates directing verbs into camera moves and rhythm`

---

### Task 4: WorldStage — 자동 카메라 실행

**Files:**
- Modify: `src/film/WorldStage.tsx`

- [ ] **Step 1: 콘텐츠를 `.film-cam-auto` 그룹으로 감싼다** (수동 카메라 `<g transform={camTransform}>` 안쪽) — 수동×자동이 중첩 합성되고 GSAP과 React가 서로 다른 노드를 만진다
- [ ] **Step 2: 초기화에 자동 카메라 리셋 추가** — `gsap.set(q('.film-cam-auto')!, { x: 0, y: 0, scale: 1 })`
- [ ] **Step 3: 타임라인 케이스**

```ts
case 'camera':
  tl.to(q('.film-cam-auto')!, {
    x: m.x, y: m.y, scale: m.k,
    duration: d * 0.9, ease: 'power2.inOut', transformOrigin: '0px 0px',
  }, label)
  break
```

- [ ] **Step 4: `npx tsc -b && npx vitest run` 통과 + 커밋** — `feat: auto camera group executes zoom directions on the timeline`

---

### Task 5: 검증

- [ ] tsc·vitest 전체, oxlint 신규 경고 0
- [ ] 키 있으면 `RUN_LLM_BENCH=1` 벤치 — direction이 선택 필드이므로 통과율 유지 확인 (6/6 기대)
- [ ] 브라우저(still 모드): 정렬 코드 실행 → AI 도착 후 장면 이동(다음 장면 클릭은 seek이므로 티커 없이도 렌더됨)으로 `.film-cam-auto`의 transform이 어느 시점에 identity가 아님을 확인, 마지막 장면에서 identity 복귀 확인
- [ ] 커밋 + 완료 보고

## Self-Review

- **동사에 대상이 없다**는 설계가 계약 위험을 없앤다: AI가 좌표·이름을 넘기지 않으므로 검증할 표면이 화이트리스트 하나다. 대상 해석 실패는 no-op이라 영상이 깨질 경로가 없다.
- **Type consistency**: `DirectingVerb`(Task 1) → 프롬프트(Task 2) → `Scene.direction` 소비(Task 3) → `camera` 모션(Task 3) → WorldStage 케이스(Task 4). decorateShots 시그니처 변경은 App 한 곳(Task 3에서 함께).
- **Placeholder scan**: 통과 — 캡 테스트 하나는 구조 서술이나 구현 시 실제 코드로 채운다.
