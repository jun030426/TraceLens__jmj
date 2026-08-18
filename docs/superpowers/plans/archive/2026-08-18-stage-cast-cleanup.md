# 무대 정리 — 주연만 무대에 (BFS 영상 피드백) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BFS 미로 코드 실행 영상(2026-08-18 녹화)에서 확인된 무대 붕괴를 고친다 — 죽은 객체 잔존·상자 겹침·"tuple" 무의미 셀·조연 수십 개·deque 클래스 알약·queue 내용 미표시.

**Architecture (원칙 전환):** "모든 객체가 상자를 받는다" → **"변수가 쥔 것만 상자를 받는다."** 컨테이너 안에만 사는 객체는 부모 칸의 요약 텍스트로 나타난다. 상자의 수명은 "마지막으로 만져진 때"가 아니라 "**변수가 쥐고 있는 동안**"으로 계산하고, 놓이면 무대에서 내려간다(exitObj) — 슬롯 겹침이 원천 차단된다. 작은 프림 튜플(≤3칸)은 상자 대신 변수 알약의 값 텍스트("(1, 1)")로 인라인 표시한다.

**Tech Stack:** TypeScript, vitest. 트레이서는 deque 1줄 추가 외 불변. 스키마 계약 불변.

## Global Constraints

- 화면의 모든 값은 TraceEvent에서만 (요약 텍스트도 트레이스 값의 압축일 뿐)
- 기존 테스트 167개 통과 유지, 커밋 서명 유지, 각 태스크 후 tsc+vitest
- objects 맵·locals 맵은 계속 전체를 추적한다 (compare 접지·요약 렌더에 필요) — 필터는 "무대에 올리는가"에만 적용

## 캐스팅 규칙 (단일 정의 — buildStage가 판정)

| 대상 | 무대 | 근거 |
|---|---|---|
| 변수가 한 번이라도 쥔 리스트·dict·set·deque·큰 튜플 | 상자 | 이름이 있는 것만 그린다 |
| 변수가 쥔 작은 프림 튜플 (원소 ≤3, 전부 prim) | 상자 없음 — 알약 값 "(1, 1)" | 불변이라 상자로 볼 사건이 없다 |
| 컨테이너 안에만 있는 객체 (큐 속 튜플, maze 행…) | 상자 없음 — 부모 칸 요약 "[0,0,1,0]" | 조연은 대사 없음 |
| 함수·클래스·모듈에 묶인 변수 (`deque`, `build`) | 알약도 없음 | 데이터가 아니다 |
| 상자의 수명 | 변수가 쥔 마지막 순간까지, 지나면 exitObj | 잔존·겹침 차단 |

---

### Task 1: tracer — deque를 시퀀스로

**Files:** `src/trace/py/tracer.py`, `src/trace/py/tracer_test.py`

- [ ] `import collections` 추가, 시퀀스 분기를 `isinstance(v, (list, tuple, set, collections.deque))`로 확장
- [ ] tracer_test.py에 deque 케이스 1개 (items 직렬화 확인), 로컬 CPython으로 실행 확인
- [ ] Commit: `feat: tracer serializes deque as a sequence`

### Task 2: buildStage — 보유 기반 수명 + 캐스팅 판정

**Files:** `src/film/types.ts`, `src/film/buildStage.ts`, test `src/film/buildStage.test.ts`

**Interfaces:**
- `CastObject`에 변화 없음 — **plan.objects에는 상자 받는 객체만 남는다** (필터)
- `CastVariable`에 변화 없음 — **plan.variables에서 callable-전용 변수 제거**
- 수명: 이벤트마다 "현재 어떤 변수든 쥐고 있는 객체"의 `life.to = e.seq`로 연장. 바인딩 해제는 ① 다른 값으로 재대입 ② 변수 delete ③ 비모듈 프레임 return
- 인라인 튜플 판정: `type==='tuple' && items 전부 prim && length<=3` → 상자 제외
- callable 판정: 참조 대상 ObjectSnap이 `unsupported`이고 type ∈ {function, builtin_function_or_method, method, type, module}

- [ ] 실패 테스트: (a) 컨테이너-전용 객체는 plan.objects에 없다 (b) 변수 재대입 후 옛 객체 life.to가 재대입 시점을 넘지 않는다 (c) 계속 쥔 객체(maze류)는 life.to가 마지막 이벤트까지 (d) 작은 프림 튜플 변수는 상자 없음 (e) 함수에 묶인 변수는 plan.variables에 없음
- [ ] 구현 → 통과 → Commit: `feat: stage casting — only variable-held objects get boxes, held-based lifetimes`

### Task 3: choreograph — 요약 텍스트 + 캐스트 가드 + 퇴장

**Files:** `src/film/choreograph.ts`, test

**Interfaces:**
- `shortText` 1단계 재귀: ref → 컨테이너면 `(0, 0)` / `[0,0,1,0]` / `{a:1}` 스타일 요약 (12자 절단, 깊이 1에서 타입명), 아니면 타입명
- cast 가드: `castObjects/castVars = plan에서 파생`. 비캐스트 객체·변수의 델타는 모션 없음 (objects/locals 맵 추적은 유지)
- 변수 ref 대입: 캐스트 객체면 bind(끈), 아니면 `setVar(요약 텍스트)` — 인라인 튜플이 "(1, 1)"로 알약에 표시
- 퇴장: 이벤트마다 `life.to < e.seq`인 등장 완료 상자에 exitObj (1회)
- flushLapse·frameVars·비교 접지 로직에 같은 가드 적용

- [ ] 실패 테스트: (a) 컨테이너-전용 객체에 enterObj/grow 없음 (b) 인라인 튜플 대입이 setVar "(1, 1)" (c) 재대입으로 놓인 상자에 exitObj 발생 (d) maze형(계속 쥠)은 exitObj 없음 (e) 리스트 칸에 튜플 요약 텍스트
- [ ] 구현 → 통과 → Commit: `feat: cast-guarded motions, one-level summaries, exit on release`

### Task 4: E2E — BFS 재현 검증

- [ ] BFS 미로 코드 재현 실행 (still 프로브): 상자 수 ≤ 7 (maze·queue·visited·path·directions±churn), 같은 슬롯 동시 가시 0건, `deque` 알약 없음, queue 칸에 요약 텍스트, path 칸 "(0, 0)" 형태
- [ ] 전체 스위트 + lint + 커밋

## Self-Review
- 캐스팅 판정이 buildStage 한 곳: choreograph·layout·WorldStage는 plan을 소비만 — 판정 이중화 없음
- objects/locals 전체 추적 유지로 compare·요약이 계속 접지됨
- 위험: 보유-기반 수명 계산의 프레임 return 처리 누락 시 잔존 재발 → 테스트 (c)(d)로 고정
