# docs/superpowers — 문서 지도

팀 3인의 설계·계획·실측 기록. **구조 규칙:** specs는 "무엇을 왜"(설계·계약·보고서), plans는 "어떻게"(구현 계획). 실행이 끝난 plan은 `plans/archive/`로 내린다 — plans 루트에는 지금 진행 중인 계획만 남는다.

## 기획 변천 한눈에

| 시기 | 전환 | 근거 문서 |
|---|---|---|
| 08-11 | 기획 동결 (v3.1) — Pyodide 트레이서 + 규칙/AI 대본 + 플레이어 | `specs/2026-08-11-algo-scope-design.md` |
| 08-11 | 필름 엔진 — 스텝 재생을 "무성영화"(모션 연속체)로 | `plans/archive/2026-08-11-film-engine.md` |
| 08-16 | 연출 동사·피드백 2차 — AI가 완급·확대·여운을 지시 | `specs/2026-08-16-feedback-round2-design.md` |
| 08-18 | 연출 무대 — 고정 배치도 대신 구성(compose)·카메라·이름표 (끈 제거) | `plans/archive/2026-08-18-cinematic-stage.md` |
| 08-18 | 학습자 시선 — 필름 자막·값 이동·정직한 배지·최종 프레임 진실 | `specs/2026-08-18-learner-flow-film-design.md` |
| 08-18 | **은유 스킨 = 유일한 베이스** — 막대·저울·스핀·스윕, 색 4역할, 정밀 모드 삭제 | `specs/2026-08-18-intro-metaphor-skin-design.md` |
| 08-18 | **기획 동결 해제** — 살아있는 설계서로 전환, 파이프라인·스키마·시각 언어 전면 현행화 | `specs/tracelens-design.md` ← **현재 기준** |

## specs — 살아있는 문서

| 문서 | 성격 | 상태 |
|---|---|---|
| `tracelens-design.md` | **살아있는 설계서 — 현재 기준.** 결정은 부록 A에 기록한 것만 | **기준 문서** |
| `2026-08-11-algo-scope-design.md` | 구 기획 동결본 v3.1 | 대체됨 — 동결 시점 이력으로 보존 |
| `2026-08-11-algo-scope-glossary.md` | 용어 해설 | 유효 |
| `2026-08-11-pilot-guide.md` | 파일럿 진행 가이드 | 유효 — 08-18 갱신 절 필독 (끈→이름표, 저울, 길이 재실측) |
| `2026-08-18-learner-flow-film-design.md` | 학습자 흐름 진단·원칙 | 유효 (설계서 5절에 원칙 흡수됨) |
| `2026-08-18-intro-metaphor-skin-design.md` | 은유 스킨 설계 + 개정 | 유효 (설계서 5절에 계약 흡수됨) |
| `TraceLens_기획안_v3.pdf` · `TraceLens_용어해설.pdf` | 원본 기획 자료 | 보관 |

## specs — 실측 보고서 (기록)

- `2026-08-11-tracer-spike-report.md` — 트레이서 Go/No-Go 실측
- `2026-08-11-benchmark-report.md` — 유형별 파이프라인·LLM 통과율 (하네스는 `src/bench/`에 상시 회귀로 살아있음)
- `2026-08-16-feedback-round2-design.md` — 피드백 2차 설계 (구현 완료, 결정 근거 기록)

## plans

- (현재 진행 중인 계획 없음 — 다음: 은유 2단계 [행위자·함수 작업대·이야기 자막] 착수 시 신규 작성)
- `archive/` — 실행 완료된 계획 11편 (08-11 MVP·필름 엔진부터 08-18 학습자 흐름까지)
