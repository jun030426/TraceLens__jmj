# TraceLens 기술 벤치마크 보고서 (1차)

- 일자: 2026-08-11 · 기획안 검증 과제 "기술 벤치마크"의 첫 실측
- 샘플: 유형별 층화 18개 (9개 유형 × 2) — 제어 흐름 / 함수 / 재귀 / mutation / aliasing / 중첩 데이터 / 예외 / 클래스 / 컴프리헨션
- 범위 밖 유형(generator·input 등)은 기획대로 제외
- 하네스: `src/bench/pipeline.bench.test.ts` (회귀 테스트로 상시 실행) + `llmPass.bench.test.ts` (RUN_LLM_BENCH=1로 실측)

## 결과 요약

| 지표 | 결과 | 스파이크 보고서의 제안 기준 |
|---|---|---|
| 파이프라인 완주율 (규칙 기반) | **18/18 = 100%** | — |
| Tracer 정확성 (기록 stdout ↔ 실제 실행 출력 일치) | **18/18 = 100%** | 100% 요구 충족 |
| 예외 기록 정확성 | 2/2 (IndexError·KeyError 종류까지 일치) | — |
| 자막 무결성 (미치환 플레이스홀더 0, seq 단조성) | 18/18 | — |
| Digest 압축률 (원본 대비) | 평균 **53%** (38~67%) | — |
| **LLM 대본 검증 통과율** (Gemini 2.5 Flash, 재시도 ≤1 포함) | **6/6 = 100%** | — |

## 샘플별 상세

| 유형 | 샘플 | 이벤트 | 재생 스텝 | Digest 크기 |
|---|---|---|---|---|
| 제어 흐름 | control-if | 7 | 7 | 67% |
| 제어 흐름 | control-while | 15 | 10 (접힘) | 39% |
| 함수 | function-basic | 8 | 8 | 60% |
| 함수 | function-nested | 14 | 14 | 62% |
| 재귀 | recursion-fact | 24 | 24 | 66% |
| 재귀 | recursion-sum | 24 | 24 | 57% |
| mutation | mutation-list | 7 | 7 | 49% |
| mutation | mutation-dict | 6 | 6 | 50% |
| aliasing | aliasing-basic | 6 | 6 | 54% |
| aliasing | aliasing-nested | 5 | 5 | 47% |
| 중첩 데이터 | nested-data | 6 | 6 | 43% |
| 중첩 데이터 | nested-list | 5 | 5 | 42% |
| 예외 | exception-index | 5 | 5 | 61% |
| 예외 | exception-key | 5 | 5 | 61% |
| 클래스 | class-basic | 14 | 14 | 54% |
| 클래스 | class-method | 21 | 21 | 59% |
| 컴프리헨션 | comprehension-list | 9 | 8 | 38% |
| 컴프리헨션 | comprehension-dict | 8 | 8 | 43% |

LLM 실측 대상 6개: aliasing-basic · recursion-fact · control-while · mutation-dict · exception-index · class-method — 전부 3단계 검증(스키마·참조·순서) 통과.

## 해석과 한계

- **Tracer 정확성 100%는 "기록이 곧 사실"이라는 제품 주장의 근거 수치다.** 순수 실행의 stdout과 트레이스에 기록된 stdout을 별도 경로로 비교했다.
- 재귀 샘플의 재생 스텝(24)이 접히지 않은 것은 재귀가 같은 줄이라도 프레임이 달라 접기 대상이 아니기 때문 — 의도된 동작이나, 깊은 재귀에선 스텝이 길어질 수 있어 "프레임 묶음 접기"가 향후 개선 후보.
- Digest 압축률 53%는 소형 샘플 기준 — 압축의 진가는 대형 트레이스(루프 접기)에서 나타난다 (control-while 39%가 그 방향의 신호).
- LLM 통과율 6/6은 표본이 작다 (무료 티어 속도 제한 고려). 본 개발에서 샘플을 50~100개로 늘려 유형별 통과율·폴백률을 측정하는 것이 다음 단계.
- 이 벤치마크는 로컬 CPython 트레이스 기준이며, 브라우저(Pyodide) E2E 지연은 별도 측정 항목.
