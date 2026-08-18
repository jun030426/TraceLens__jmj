# 무대 지정(staging) — AI의 표현 선택 노브 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "이 자료를 격자로 봐라 / 보지 마라"를 AI 대본이 선택할 수 있게 한다 — 선택은 AI, 판정·좌표·렌더는 도구, 규칙 판정은 폴백. 이로써 규칙이 못 하는 의미 판단(`["hello","world"]`는 문자열 목록이지만 `["S.#","..#"]`는 보드다)이 AI의 자리로 들어온다.

**Architecture:** Screenplay 최상위에 `staging: { grid: string[], noGrid: string[] }`(변수명, digest 등장 이름만 유효). AI 대본 도착 시 힌트가 규칙 판정과 다르면 **필름을 재구축**(buildStage(events, staging) → layout → choreograph → decorate)하고 재생 위치는 seq로 복원한다. 같으면 기존 장식-만 경로 그대로(재구축 없음 — 흔한 경우 무비용). `grid` 힌트는 확장 판정을 연다: 균일 2차원 프림 리스트(기존) **+ 같은 길이 문자열 행 리스트**(`["S.#","..#"]` — 규칙만으로 켜면 `["hello","world"]` 오탐이라 AI 게이트가 정확히 맞는 자리). `noGrid`는 규칙이 격자로 판정한 것을 상자로 강제. AI 없음·실패·무효 이름 = 규칙 판정 그대로.

**Tech Stack:** TypeScript, vitest. 트레이서 불변. 값·좌표는 여전히 트레이스에서만.

## Global Constraints

- AI는 변수명 선택만 — 좌표·값·판정 로직을 쓰지 않는다. 격자 자격 검사(균일성·크기 ≤400칸)는 항상 도구가 한다: 자격 미달 grid 힌트는 조용히 무시(상자 폴백)
- staging 이름은 digest의 changedVars에 등장한 이름만 통과 (지어낸 이름 차단)
- 기존 186 테스트 통과 유지, 각 태스크 후 tsc+vitest, 커밋 서명 유지
- 주인공(lead) 지정은 이번 라운드 보류 — 소비자(lead를 쓰는 렌더 동작)가 아직 없어서 노브만 만들면 장식 없는 스위치가 된다. 카메라 기본 타깃 등 소비자가 생길 때 함께 넣는다

---

### Task 1: 스키마 + 리졸버 — staging 파싱

**Files:** `src/screenplay/types.ts`, `src/director/resolver.ts`, test `resolver.test.ts`

**Interfaces:** `Screenplay.staging?: { grid: string[]; noGrid: string[] }`. resolveScreenplay·salvageScreenplay 둘 다: `raw.staging`에서 문자열만·중복 제거·digest 변수명(스팬 changedVars 합집합)에 있는 이름만. 필드 없거나 전부 무효면 staging 자체 생략.

- [ ] 실패 테스트: (a) 유효 이름만 남는다 (b) digest에 없는 이름은 걸러진다 (c) 배열 아니면 생략 (d) salvage 경로도 staging을 나른다
- [ ] 구현 → 통과 → Commit: `feat: staging hints in the screenplay contract — names only, digest-validated`

### Task 2: buildStage — 힌트 적용 + 문자열 행 격자

**Files:** `src/film/buildStage.ts`, test

**Interfaces:** `buildStage(events, staging?: { grid?: string[]; noGrid?: string[] })`. 이름 → 그 이름의 변수가 쥐었던 모든 객체로 해석. `noGrid` 객체는 격자 판정 스킵(상자). `grid` 객체는 확장 판정: 기존 2D 프림 리스트 **또는** "원소 전부 같은 길이(≥2) 문자열 프림, 행 ≥2, 총 ≤400칸" → `grid { rows, cols, binary }` (문자열 행은 binary=false, cols=글자 수 — repr 따옴표 제외).

- [ ] 실패 테스트: (a) noGrid로 maze형이 상자가 된다 (b) grid 힌트로 문자열 행 리스트가 격자가 된다 (rows·cols 정확) (c) 힌트 없으면 문자열 리스트는 상자 (d) 자격 미달 grid 힌트(들쭉 길이)는 무시
- [ ] 구현 → 통과 → Commit: `feat: staging hints steer grid detection — AI unlocks string-row boards`

### Task 3: choreograph — 문자열 행 격자의 칸 텍스트

**Files:** `src/film/choreograph.ts`, test

gridTextsOf가 행 원소가 문자열 프림이면 repr 따옴표를 벗기고 글자 단위로 칸을 채운다. 문자열은 불변이라 rowToGrid 경로 불필요 — outer 델타만으로 갱신된다.

- [ ] 실패 테스트: 문자열 격자 등장 시 gridCell 텍스트가 글자('S','.','#')다
- [ ] 구현 → 통과 → Commit: `feat: string-row grids fill cells character by character`

### Task 4: 프롬프트 + App 재구축 경로

**Files:** `src/director/llmDirector.ts`, `src/App.tsx`

- 프롬프트: 출력 형식에 최상위 `"staging":{"grid":["변수명"],"noGrid":[]}` 추가 + 규칙 11: 공간으로 이해할 자료(표·보드·미로·DP 테이블·같은 길이 문자열 행)는 grid에, 표가 아닌데 격자로 그려질 자료는 noGrid에, 확신 없으면 생략
- App: `RunArtifacts.events` 보관. AI 도착 시 staging이 있으면 `buildStage(events, staging)` 재판정 → **격자 구성이 기존 plan과 다르면** 전체 재구축(layout·choreograph·decorate), 같으면 기존 장식-만 경로. 재생 위치 복원을 index → **seq 기준**으로 교체(재구축은 샷 수가 달라진다): restoreRef가 현재 샷 seq를 저장, 복원 effect가 `새 shots에서 seq ≤ 저장값인 마지막 인덱스`로 seek
- [ ] tsc+vitest 통과 → Commit: `feat: AI staging rebuilds the film — position restored by seq`

### Task 5: E2E 검증

- [ ] 문자열 미로 코드(`maze = ["S.#","...","#.G"]` + 탐색)로 실행 → AI 응답 캡처로 staging.grid 방출 확인 → 격자 등장(gcell 글자) 확인. AI가 staging을 안 내면: 콘솔에서 스크린플레이에 staging 주입해 재구축 경로 자체를 검증
- [ ] BFS 회귀: 프림 격자는 힌트 유무와 무관하게 동일(재구축 조건 미충족 → 장식-만 경로)
- [ ] 전체 스위트 + lint → Commit

## Self-Review
- 힌트의 힘은 정확히 "규칙이 못 하는 의미 판단"에만 있다: 프림 2D는 이미 자동이라 grid 힌트가 무해하고, 문자열 행은 오탐 위험 때문에 AI 전용이 맞다
- 재구축은 조건부(격자 구성 변화 시)라 흔한 경로의 비용·출렁임이 없다. seq 복원은 장식-만 경로에서도 동작(동일 seq 집합)
- 실패 사다리 불변: staging 무효·AI 실패 → 규칙 판정 영화 그대로
