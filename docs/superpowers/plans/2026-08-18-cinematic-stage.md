# 연출 무대 (Cinematic Stage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** "움직이는 회로도"를 애니메이션으로 바꾼다 — 모든 배우가 지정석에 고정된 배치도 대신, **지금 일어나는 일이 중앙에 크게, 최근 것은 옆에 작게, 나머지는 무대 밖**. 끈(전선)은 없애고 값이 실제로 이동한다.

**Architecture:** 새 패스 `compose(shots, plan, layout)`가 샷마다 **구성(Composition)** — 무대에 올릴 배우와 위치·배율 — 을 결정적으로 계산한다(이번 샷에 닿은 배우 = 포커스·중앙, 최근 LINGER샷 내 배우 = 대기열·축소, 그 외 퇴장). WorldStage는 배우를 **로컬 좌표로 그리고 transform으로 배치**하며, 구성이 바뀔 때 GSAP이 이동·확대·페이드 전환한다. 배우 가시성의 단일 소유자는 구성이다(enterObj/exitObj의 불투명도 트윈 제거 — 죽은 배우는 더는 닿지 않으므로 자연히 구성에서 빠진다). 끈 제거, 칸 번호는 포커스 배우에만, popleft처럼 "칸이 빠지고 같은 샷에 변수가 그 값을 받는" 순간은 **칩이 날아가는 이동 애니메이션**으로 잇는다.

**브랜치:** `feat/cinematic-stage` — 파일럿 데모(`feat/slice-1`)는 그대로 두고, 여기서 검증 후 합류 여부 결정.

## Global Constraints

- 값·순서는 트레이스에서만. 구성은 "무엇을 보여줄까"이지 사실 변경이 아니다 — 무대 밖 상태는 인스펙터가 항상 들고 있다
- choreograph 모션 계약 불변(의미 층). 변경은 compose(신규)와 WorldStage(연출 층)
- still 모드: 모든 전환 duration ×0.001, 최종 프레임 완성 유지
- 기존 200 테스트 통과 유지, 각 태스크 후 tsc+vitest

## Tasks

### Task 1: compose — 구성 계산 (신규 `src/film/compose.ts` + tests)
- 입력: shots·plan·layout(크기만 소비). 출력: 샷별 `Map<actorKey, Placement { x, y, s, focus }>`
- 규칙: 이번 샷에 모션이 닿은 배우 = focus(중앙 열, s=1) / 최근 6샷 내 = 대기(우측 열, s=0.55) / 그 외 무대 밖. 변수는 좌측 스트립(최근순 ≤8, focus s=1 · 대기 s=0.8)
- sticky: 이어지는 배우는 이전 세로 순서를 유지(출렁임 방지), 새 배우는 뒤에
- 같은 열 안에서 세로 겹침 금지(배율 반영한 높이 + 간격으로 패킹), 필요 시 무대 높이 반환
- 테스트: 포커스 판정·대기 강등·LINGER 초과 퇴장·스트립 상한·같은 열 무겹침·sticky 순서

### Task 2: WorldStage — 로컬 좌표 + 구성 전환
- 배우(상자·격자·알약)를 (0,0) 기준으로 그리고 바깥 `<g data-*>`에 transform. 안쪽 `.actor-inner` 래퍼(펄스가 구성 배율과 싸우지 않게)
- 구성 diff → 이동·확대 트윈(0.45s), 등장(아래서 페이드 인)·퇴장(축소 페이드 아웃). `is-focus` 클래스( 기존 is-live의 accent 스타일 계승, 칸 번호도 포커스만 표시)
- 끈 완전 제거. enterObj/exitObj/enterVar/exitVar의 불투명도 트윈 제거(라벨 갱신만 유지)
- 격자 커서·경로·칸은 로컬 좌표(오히려 단순해짐). 프레임·출력 바·오류 스트립은 하단 HUD 그룹으로 묶어 무대 높이에 맞춰 이동
- Task 1과 같은 커밋 흐름에서 검증: tsc + 전체 테스트 + BFS still 프로브

### Task 3: 이동 애니메이션 (칩)
- 무대에 칩 2개를 미리 만들어 풀로 재사용 (스크럽 안전)
- 규칙 v1: ① 같은 샷에 shrink(상자)+setVar(변수)가 있으면 그 칸 → 그 알약으로 칩이 날아간다 (popleft의 그림) ② grow는 상자 위에서 내려앉는다 ③ bind는 알약 → 상자로
- 좌표는 구성에서 (build 시점에 알고 있음)

### Task 4: 카메라·CSS 마무리
- decorate의 zoom: 대상 rect 조준 → 중앙 당김(k만)으로 단순화 (구성이 이미 액션을 중앙에 두므로) + 테스트 갱신
- CSS: `.is-focus` accent 스타일, 포커스-온리 번호, 칩 스타일

### Task 5: E2E
- BFS·정렬 still 프로브: 구성 겹침 0, 무대 밖 배우 opacity 0, 포커스 배우 중앙·s=1, 칩 요소 존재, 격자·커서·경로 회귀 없음
- 커밋 + 사용자 라이브 확인 안내 (브랜치 전환법 포함)

## Self-Review
- 가시성 소유권을 구성으로 단일화한 것이 핵심 — 생애 모션과 구성이 불투명도를 두 군데서 쓰면 다시 유령이 생긴다
- 위험: 위치가 움직이면 물체 정체성 인지가 흔들릴 수 있다(고정 무대를 택했던 이유). sticky 순서 + 이동 트윈(순간이동 금지) + 이름표가 그 보험이다. 파일럿 전 라이브 시청으로 판단하고, 아니다 싶으면 feat/slice-1로 복귀
