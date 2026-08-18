# 상자 이름표 + 강조 강화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ① 오른쪽 상자·격자 **위에 그것을 쥔 변수명**을 크게 표시(끈을 따라가지 않아도 어느 상자가 maze인지 보이게) ② 상자 테두리를 진하게 ③ 값 변경(알약 값·칸 값·격자 칸)을 더 강하게 강조.

**Architecture:** 이름표는 동적이다 — 재대입·별칭·프레임 반환으로 쥔 이름이 바뀌므로, choreograph가 보유 변화를 추적해 `label { objectId, text }` 모션을 방출하고 WorldStage가 상자 위 텍스트를 갱신한다. 별칭이면 "a · b"로 두 이름이 함께 걸린다(별칭의 그림 그 자체). 타입·크기 표기는 상자 오른쪽 위로 옮겨 보조 정보가 된다. 강조는 기존 펄스의 진폭·획 두께 강화 + 격자 칸 변경 펄스(초기 채움 제외 — `flash` 플래그).

## Tasks

### Task 1: choreograph — label 모션
- Motion에 `{ v: 'label'; objectId: number; text: string }`, gridCell에 `flash?: boolean`(변경일 때만 true, 초기 채움 false)
- 보유 이름 추적: bind(캐스트) → 옛 상자에서 이름 제거·재라벨 + 새 상자에 추가·재라벨 / prim·인라인 재대입, exitVar, 프레임 반환 → 제거·재라벨
- 테스트: (a) bind에 변수명 라벨 (b) 재대입 시 옛 상자 라벨에서 이름 빠짐 (c) 별칭이면 "a · b" (d) 격자 변경 gridCell만 flash
- Commit: `feat: boxes wear their holders' names — dynamic labels, alias shows both`

### Task 2: WorldStage + CSS — 렌더·강조
- 상자·격자 상단 왼쪽에 이름 텍스트(`.film-obj-name`, svg-name — 데이터라 mono d-lg), 타입·크기는 오른쪽 끝(svg-type, 정적)
- 컨테이너 rect: stroke line→line-strong, 폭 1.4→2 (상자·격자)
- setVar 펄스 1.14→1.28 / setCell 1.2→1.35 + 획 두께 펄스 / gridCell flash → 칸 펄스
- label 케이스: 텍스트 교체
- Commit: `feat: bolder boxes, stronger change emphasis`

### Task 3: 검증
- tsc + vitest 전체, BFS still 프로브로 라벨 텍스트(maze·queue·visited…) 확인, 커밋
