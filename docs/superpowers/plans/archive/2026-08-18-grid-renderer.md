# 격자 렌더러 — 대표 시각화 2호 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2차원 프림 리스트(maze·DP 테이블)를 한 줄 상자가 아니라 **격자**로 그리고, 그 위에 방문 칠하기(visited)·현재 위치 커서(좌표 변수)·경로 선(좌표 리스트)을 얹는다 — "알고리즘의 이야기"가 자막 없이 읽히게.

**Architecture:** 판정은 전부 결정적이고 buildStage 한 곳에서 한다: ① **격자** = 변수가 쥔 list이면서 모든 원소가 "프림만 담은 같은 길이의 list"(행 2+, 열 2+, ≤400칸). ② **방문 집합** = 캐스트 set이면서 원소 전부가 어떤 살아있는 격자의 범위 안 좌표 튜플. ③ **커서** = 인라인 좌표 튜플을 쥔 변수의 값 변경. ④ **경로 선** = 캐스트 list이면서 원소 전부가 범위 안 좌표 튜플. 렌더는 새 모션 4종(gridCell·gridVisit·gridCursor·gridTrail)으로, 색은 기존 문법 그대로(벽=line-strong, 방문=accent-wash/accent, 커서·경로=accent). AI 계약 불변 — zoom이 격자 rect를 자동으로 잡는다.

**Tech Stack:** TypeScript, SVG+GSAP, vitest. 트레이서·스키마 계약 불변.

## Global Constraints

- 격자·오버레이의 모든 값·좌표는 TraceEvent에서만 (0/1 값, visited 내용, position 값 전부 트레이스에 있음)
- 판정 실패 시 기존 한 줄 상자로 자연 폴백 — 빈 화면 경로 없음
- 색 토큰 규칙: 격자도 Drawn-State 문법(쉼=panel/line, 벽=line-strong 면, 지나간·현재=accent 계열)만 사용
- 기존 175 테스트 통과 유지, 각 태스크 후 tsc+vitest, 커밋 서명 유지

## 화면 문법

| 요소 | 그림 | 근거 데이터 |
|---|---|---|
| 격자 칸 | 정사각 칸, 모서리 공유(연속 메모리 관례) + 칸 값 텍스트(d-xs) | maze[r][c] 값 |
| 벽 (0/1 격자의 1) | line-strong 면 | 값 ≠ 0 |
| 방문한 칸 | accent-wash 면 + accent 획 (누적) | visited set 내용 |
| 현재 위치 | accent 원(커서), 칸 중심으로 이동 트윈 | 좌표 튜플 변수의 최신 값 |
| 경로 | accent 폴리라인 (칸 중심 연결) | 좌표 리스트의 내용 |
| 행·열 번호 | 격자 밖 상단·좌측, ink-3 모노 d-xs | 인덱스 |

---

### Task 1: buildStage — 격자 판정

**Files:** `src/film/types.ts`, `src/film/buildStage.ts`, test `buildStage.test.ts`

**Interfaces:** `CastObject`에 `grid?: { rows: number; cols: number; binary: boolean }` (binary = 모든 칸이 '0'|'1' — 벽 스타일 적용 여부). 최신 스냅 기준 판정: type list · 행 2+ 전부 ref → 각 행 type list · 열 2+ 전부 prim · 열 길이 동일 · rows×cols ≤ 400.

- [ ] 실패 테스트: (a) maze형 이벤트 → plan 객체에 grid {rows:4, cols:4, binary:true} (b) 행 길이 불일치 → grid 없음 (c) 1차원 프림 리스트 → grid 없음 (d) 숫자 DP 테이블 → binary:false
- [ ] 구현 → 통과 → Commit: `feat: grid detection — uniform 2D prim lists become grids`

### Task 2: layout — 격자 발자국

**Files:** `src/film/layout.ts`, test

**Interfaces:** 격자는 슬롯 행이 아니라 2D 발자국: 칸 34px, `w=cols*34+16`, `h=rows*34+16`, x=OBJ_X에서 위부터 쌓임(간격 40). 일반 상자 슬롯 행들은 격자 무리 아래에서 시작. 높이 계산에 격자 포함.

- [ ] 실패 테스트: (a) 격자 rect가 rows·cols 비례 (b) 일반 상자가 격자 아래에서 시작 (c) 겹침 금지 기존 테스트 유지
- [ ] 구현 → 통과 → Commit: `feat: grids get a 2D footprint, row boxes stack below`

### Task 3: choreograph — 격자 모션

**Files:** `src/film/types.ts`, `src/film/choreograph.ts`, test

**Interfaces:** Motion 추가:

```ts
| { v: 'gridCell'; objectId: number; r: number; c: number; text: string; wall: boolean }
| { v: 'gridVisit'; objectId: number; r: number; c: number }
| { v: 'gridUnvisit'; objectId: number; r: number; c: number }
| { v: 'gridCursor'; objectId: number; r: number; c: number }
| { v: 'gridTrail'; objectId: number; points: [number, number][] }
```

방출 규칙 (전부 결정적):
- 격자 객체의 델타 → 기존 상자 diff 대신 격자 diff: 최초 set = enterObj + 전 칸 gridCell, 이후 outer/inner-row set = 바뀐 칸만 gridCell (rowToGrid: 격자 스냅의 행 ref → {gridId, r} 등록; 행은 조연이지만 격자 갱신의 통로)
- 캐스트 set의 원소가 전부 어떤 격자 범위 안 좌표 튜플 → added/removed 좌표에 gridVisit/gridUnvisit (set 상자는 그대로 유지 — 자료구조 뷰와 공간 뷰의 대응을 보여줌)
- 캐스트 변수에 인라인 좌표 튜플 대입 → setVar(기존) + gridCursor (마지막 대입이 커서를 가짐)
- 캐스트 list의 원소가 전부 범위 안 좌표 튜플 → 내용 변경 시 gridTrail(전체 points)
- 격자 퇴장은 기존 exitObj 수명 규칙 그대로

- [ ] 실패 테스트: (a) 격자 최초 등장에 gridCell 16개+wall 플래그 (b) visited.add → 올바른 (r,c)의 gridVisit (c) 좌표 변수 대입 → gridCursor (d) path형 리스트 → gridTrail points (e) DP형 안쪽 행 변경 → 해당 칸 gridCell
- [ ] 구현 → 통과 → Commit: `feat: grid motions — cell fills, visit paint, cursor, trail`

### Task 4: WorldStage + CSS — 격자 실행

**Files:** `src/film/WorldStage.tsx`, `src/ui/app.css`

- 렌더: `o.grid`면 상자 대신 격자 마크업 — 바깥 rect(sunken/line), 칸 rect `data-gcell="${id}-${r}-${c}"`(panel/line, 모서리 공유), 칸 값 text, 행·열 번호(svg-index), 커서 `data-gcursor`(r=7 accent 원, 숨김), 경로 `data-gtrail`(polyline, 숨김)
- 모션 케이스: gridCell = call(텍스트+is-wall 클래스), gridVisit/gridUnvisit = is-visited 클래스 토글(CSS 160ms 전이), gridCursor = attr cx/cy 트윈 + opacity 1, gridTrail = call(points)+opacity fromTo
- CSS: `.film-gcell { fill: var(--panel); stroke: var(--line); transition: fill 160ms var(--ease), stroke 160ms var(--ease) }`, `.is-wall { fill: var(--line-strong) }`, `.is-visited { fill: var(--accent-wash); stroke: var(--accent) }`
- [ ] tsc+vitest 통과 → Commit: `feat: grid renderer — walls, visit paint, cursor, trail on stage`

### Task 5: E2E + 도움말

- [ ] BFS 재현(still 프로브): gcell 16개, 종료 시 is-visited 7칸((0,0)…(3,3) 방문 순서), is-wall 5칸, 커서 최종 (3,3) 중심, trail points 7개, 일반 상자들은 격자 아래
- [ ] Help A-매트릭스에 행 추가: `['2차원 리스트(격자·표)', 'maze[r][c], dp[i][j]', '격자로 그리고 방문·현재 위치·경로를 그 위에 칠함']`
- [ ] 전체 스위트+lint → Commit

## Self-Review
- 판정 4종 전부 "범위 안 좌표"라는 같은 근거를 씀 — directions((-1,0)…)는 범위 밖이라 자연 배제됨 (오탐 방어)
- 격자 객체의 상자 diff와 격자 diff가 이중 방출되지 않게 분기 (Task 3에서 격자면 상자 경로 스킵)
- 방문 accent-wash 누적은 Drawn-State의 "지금"을 "지나감"으로 넓히는 것 — 격자 안에서만 허용하고 다른 그림으로 수출하지 않는다
