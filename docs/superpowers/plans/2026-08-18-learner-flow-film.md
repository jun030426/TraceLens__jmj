# 학습자 시선 필름 (Learner-Flow Film) Implementation Plan

> 스펙: `docs/superpowers/specs/2026-08-18-learner-flow-film-design.md`

**Goal:** 비전공 학습자가 흐름을 따라갈 수 있는 필름 — 무대는 안정되고, 자막은 화면과 일치하고, 판단(읽기)과 변화(쓰기)가 다른 색으로 말하고, 값이 실제로 이동한다.

**브랜치:** `feat/cinematic-stage` 계속.

## Global Constraints
- 값·순서는 트레이스에서만. 자막·여행도 모션/트레이스에서 결정적으로만 생성 (지어내지 않는다)
- still 모드: 최종 프레임 완성 유지 (`progress(1, false)`)
- 각 태스크 후 tsc + vitest 전체 통과, 마지막에 E2E 프로브

## Tasks

### Task 1: compose — sticky focus·생존 변수·완전한 커튼콜 (+tests)
- 객체: 닿은 객체가 없는 샷은 직전 focus 객체가 focus·중앙 유지(lastTouch 갱신으로 체류 연장). 다른 객체가 닿으면 그때 대기열로.
- 변수: `plan.variables`의 `life`로 생존 판정 — 살아있으면 무대 유지, MAX_VARS 초과분만 최근성으로 강등. exitVar는 여전히 즉시 퇴장.
- 커튼콜: 마지막 샷은 최종 seq 기준 살아있는 배우 전원 (lastTouch 무관).
- 테스트: 변수-only 샷에서 focus 객체 유지 / 생존 변수 비퇴장 / 커튼콜 전원 복귀.

### Task 2: choreograph — caption + 배지 정직화 + 최종값 정산 (+tests)
- `Shot.caption?: string` — 우선순위 규칙(스펙 B)으로 생성. 무조사 템플릿.
- 배지: `반복 N회째` 카운트업만. total 제거 (timelapse 문구는 유지).
- 모듈 return 시 살아있는 프림 변수 최종값 setVar 정산.
- 비교 샷 MED_MS(850ms).
- 테스트: swap+비교 조합 자막 / setVar 자막 / 배지 문자열 / 최종값 정산 / 비교 샷 길이.

### Task 3: choreograph — travel 모션 + WorldStage 통합 핸들러 (+tests)
- Motion에 `travel` 추가. shrink+setVar 추론을 WorldStage에서 제거하고 choreograph가 방출.
- 라인 접지 확장: `x = NAME[i]`(칸→알약), `NAME.append(x)`·`NAME[i] = x`(알약→칸). `causedByLine` 기준, resolveOperand 재사용.
- WorldStage: travel 모션 하나로 칩 비행 (기존 칩 풀 재사용, 구성 좌표 매핑).
- 테스트: 접지 성공/침묵 케이스, popleft 회귀.

### Task 4: WorldStage — 인과 echo·캐스케이드·커튼콜 settle·색 언어 (+CSS)
- swap 샷에 직전 참 비교 칩 재표시 (choreograph가 compare echo 모션 재방출).
- 같은 샷 다중 grow는 칸 순서 계단식 등장 (still 모드 안전: sec() 배율).
- 커튼콜 settle 웨이브 (칸 순서 잔잔한 펄스).
- 칸·알약 플래시 오버레이 rect + 쓰기 트윈(opacity 1→0), 읽기는 파란 링 트윈. 클래스 토글 금지(스크럽 안전).
- CSS: `.cell-flash`·`.pill-flash`·읽기 링 색 토큰.

### Task 5: App 자막 배선 + E2E
- `PlaybackStep.folded` 마커, App: 규칙 연출 = caption 우선, AI 연출 = 접힌 구간만 caption.
- E2E: 버블 정렬 + BFS still/seek 프로브 — 자막-모션 일치, 최종 프레임 진실, 겹침 0, 격자 회귀 없음.
- lint + tsc + vitest 전체, 커밋.

## Self-Review
- 위험: sticky focus가 lastTouch를 갱신하면 "영원히 안 내려가는 상자"가 생길 수 있다 — 다른 객체가 닿는 순간 물러나므로 무대 독점은 이야기가 실제로 한 배우뿐일 때만이다. 그건 올바른 연출이다.
- 위험: travel 접지의 오탐 — 해석 실패·모호하면 침묵이 기본값. 비교 접지와 같은 보수성.
- 자막 이중화(배지 vs 자막)는 배지=상태, 자막=사건으로 역할이 다르다. 숫자 모순은 배지 total 제거로 사라진다.
