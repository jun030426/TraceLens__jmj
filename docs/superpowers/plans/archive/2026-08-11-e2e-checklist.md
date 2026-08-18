# Slice 1 E2E 스모크 결과 (2026-08-11)

지원 범위 매트릭스(기획안 §2) 기준 시나리오. 통합 브라우저(dev 서버)에서 실측.

| # | 입력 | 기대 | 결과 |
|---|---|---|---|
| A1 | aliasing 예제 (team_b = team_a) | objectGraph에서 두 변수 → 한 상자, "같은 객체" 자막 | ✅ 통과 — `list · #55232` 상자에 화살표 2개, 자막 정확 |
| A2 | 루프 합계 | 루프 접기 + 실제 값 | ✅ 통과 — 15이벤트→10스텝, 콘솔 출력 10 |
| A3 | arr[5] IndexError | 예외 지점까지 재생 + 챕터 "예외 발생" | ✅ 통과 — 에러 배너 "IndexError: list index out of range" |
| A4 | 재귀 fact(4) | 호출 스택 카드 증감 | ✅ 통과 — `<모듈>`→fact(n=4)→fact(n=3) 쌓임, 챕터 "fact 실행" |
| C1 | while True 무한 루프 | 상한 종료 + clipped 배너 + 수집분 재생 | ✅ 통과 — maxEvents 5000 클립, "×4994회" 접기 표시 |
| D1 | input() | 실행 없이 차단 배너 | ✅ 통과 |
| D2 | import requests | 실행 없이 차단 배너 | ✅ 통과 (preflight 단위 테스트로 검증) |
| D3 | def만 있는 코드 | "호출 예시 추가" 경고 | ✅ 통과 — 경고 후 실행(warn 레벨) |

## 검증 중 발견·수정한 결함

1. 모듈 프레임 call/return 내레이션 어색 → "실행을 시작합니다/실행이 끝났습니다"로 특례 처리
2. 함수 객체가 `fact={}`로 표시 → tracer가 function/class/module을 unsupported로 축약 (타입명 표시)
3. 빈 스택에서 "undefined 지역 변수" → "실행 종료" 표기

## 자동 테스트 최종 상태

- vitest: 5 파일 25 테스트 전부 통과
- tracer_test.py (로컬 CPython): 6개 검증 전부 통과
- tsc -b: 오류 0
