# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**1순위 사용자: 프로그래밍 학습자** (전공 수업·독학 중인 초중급).

- **상황**: AI(ChatGPT·Claude 등)에게 받은 Python 코드를 손에 들고 있고, 자기 프로젝트에 붙여넣기 직전이다. 텍스트 설명은 읽었지만 실행 흐름이 머릿속에 그려지지 않는다.
- **하려는 일**: 이 코드가 돌 때 값과 참조가 실제로 어떻게 변하는지 보고, 코드를 자기 것으로 만든 뒤 적용한다.
- **해결하려는 문제**: AI 코드를 이해 없이 복붙하는 습관.

"AI 생성 코드"는 기술적 제약이 아니라 **대표 사용 시나리오**다 — 사람이 쓴 코드도 동일하게 처리한다.

제작 팀은 컴퓨터공학 전공 3인(실행·트레이스 / LLM·대본 / 렌더러·UX). 캡스톤 심사·발표는 존재하는 맥락이지만, 아래 성공 기준에서 1순위로 선택되지 않았다.

## Product Purpose

**TraceLens**는 Python 코드의 실제 실행 상태를 추적해, 자동 재생되는 설명 애니메이션("무비")으로 변환하는 코드 실행 시각화 도구다.

> The trace decides what happened; the Director decides what is worth showing.
> 무슨 일이 일어났는가는 실행이 결정하고, 그중 무엇을 어떻게 보여줄지는 AI가 결정한다.

**핵심 제품 가설** (전제가 아니라 검증 대상): 실제 실행 상태를 시간적으로 시각화하면, 텍스트 설명만 제공하는 것보다 프로그램 상태 변화와 실행 흐름을 이해하는 데 도움이 된다.

**다음 구간의 성공 기준 (2026-08-11 확인)**: **배포 후 팀 외부의 실제 사용자가 코드를 붙여넣고 반복 사용하는 것.** 심사 방어 완성도, MVP 기능 완주, 이해도 실험 완주는 기획안에 살아 있는 과제이지만, 이번 구간의 성공 판정 기준으로는 선택되지 않았다 — 목적이 아니라 수단으로 다룬다.

## Positioning

이웃 제품이 그대로 복사할 수 없는 지점 3축:

1. **값의 신뢰성** — 화면에 표시되는 모든 값·순서는 실제 실행에서만 나온다. 단, 이는 "해당 실행에서 실제로 발생한 상태를 보여준다"는 뜻이지 코드가 논리적으로 옳다는 보증이 아니다.
2. **재생 모델: Debugger → Movie** — Python Tutor가 사용자가 직접 스텝을 밟는 debugger-first 경험이라면, TraceLens는 중요한 장면·속도·표현을 골라 자동 재생하는 **narrative-first** 경험이다.
3. **영상 그 이상** — 실시간 렌더이므로 언제든 일시정지하고 그 순간의 변수·객체 상태를 인스펙터로 들여다볼 수 있다. 강의 영상이 못 하는 부분.

**Core / Quality 분리**: Core(실제 trace + trace-grounded rendering + 자동 재생 + 일시정지 인스펙터)는 LLM 없이 규칙 기반 대본만으로 성립한다. LLM Director는 설명 품질을 높이는 Quality layer다. 이 구분이 "왜 AI가 필요한가"에 대한 논리 구조이며, ablation으로 정량 증명할 대상이다.

## Operating Context

- **사용 흐름**: 코드 붙여넣기 → Run → preflight 판정 → 로딩(파이프라인 실제 진행 단계 표시) → 자동 재생 → 일시정지 / 스크럽 / 배속 / 챕터 점프 → 일시정지 시 인스펙터 조회
- **레이아웃 계승 결정**: 좌측 코드 에디터(Monaco) / 우측 스테이지. 프로토타입에서 계승하기로 확정된 사실
- **실행 위치**: 코드 실행·압축·재생(①②④)은 브라우저에서, 연출 생성(③)만 외부 LLM API. 이때 **코드와 Digest가 외부로 전송된다** — 사용자 고지, opt-out(규칙 기반 폴백만 사용), local-only 모드가 제품 요구사항이다
- **콜드/웜 스타트**: 첫 방문은 Pyodide 런타임(수십 MB) 다운로드가 필요하다. 페이지 진입 시 백그라운드 선로딩으로 흡수한다
- **UI 언어**: 한국어

## Capabilities and Constraints

**파이프라인 4단계** — Tracer(Pyodide + Web Worker + `sys.settrace`) → Digest(루프 접기·압축) → Director(LLM 대본) → Player(GSAP 타임라인 + SVG). 각 모듈은 3개 스키마 계약(TraceEvent / DigestSpan / Screenplay)으로만 통신한다.

**지원 범위 매트릭스** (전문: [기획안 §2](docs/superpowers/specs/2026-08-11-algo-scope-design.md))

- **A. 완전 지원** — 변수·연산, 조건·반복, 함수·재귀, list/dict/set 조작, aliasing·얕은 복사, 예외, 클래스 인스턴스 기본, 컴프리헨션·문자열·print
- **B. Generic State View로 표시** — 트리·그래프 등 사용자 정의 구조, 깊은 중첩 데이터 (전용 그림 없음)
- **C. 상한까지만 재생** — 매우 긴 실행, 무한 루프, 대량 데이터
- **D. 범위 밖 — 실행 전 preflight 안내** — `input()`, generator/async/thread, 네트워크·파일·DB, 미지원 외부 라이브러리, 조각 코드, 호출 없는 정의

preflight는 best effort다. D를 놓치고 실행에 들어가도 런타임 에러 처리로 안전하게 내려온다.

**구조적 제약 (계약 수준)**

- **spanRef 원칙**: LLM은 seq 숫자를 생성하지 않고 존재하는 DigestSpan ID를 선택만 한다. 결정적 Resolver가 실제 구간으로 치환한다 — LLM이 실행 사실을 지어낼 경로를 구조적으로 차단
- **narration 템플릿 + 바인딩**: LLM은 값 문자열을 직접 쓰지 못한다. 관찰형(값·상태·호출·예외)은 장면 자막, 해석형(역할·중요도 판단)은 챕터 제목·요약으로 한정
- **observationally passive serializer**: 관찰이 프로그램 동작을 바꾸면 안 된다. `repr()`·`getattr()`·property는 사용자 코드를 실행할 수 있으므로 안전 타입 우선, 불확실한 객체는 `UnsupportedObject`로 축약
- **귀속 규칙**: 보여주는 것은 "모든 mutation"이 아니라 "source-line boundary에서 관측되는 상태 변화"다 (causedByLine / observedAtLine). 한 줄 안에서 변했다 되돌아온 중간 상태는 관측 대상이 아니며, 제품 문구도 그렇게 쓴다
- **예외는 실패가 아니라 콘텐츠**: 터지는 지점까지 재생하고 그 순간을 하이라이트
- **폴백 2겹**: LLM 실패·검증 불통과 → 규칙 기반 대본 / 특화 프리미티브 매핑 실패 → Generic State View. "실패해도 빈 화면은 없다"
- **렌더러**: SVG + GSAP 단일. (PixiJS 보류 자산은 2026-08-18 정리에서 의존성째 제거 — 대량 배열 병목이 실측되면 git 이력에서 검토)
- **실행 상한**: maxEvents 20,000 · 타임아웃 10초 (스파이크 실측 근거: fib(15) = 7,896 이벤트, 20k × ~300B ≈ 6MB). 사용자가 설정 화면에서 조절할 수 있다. maxSerializedBytes는 미구현

**현재 구현 상태 (2026-08-11)**

- Slice 1(실제 Tracer → 규칙 대본 → Player, LLM 없이 E2E) 완주, 태그 `slice-1`
- Slice 2 진행 중 — LLM Director(Gemini)가 기본 경로이고 실패 시 규칙 폴백으로 자동 전환
- 프로토타입 유산(`src/tracing.ts`·`src/PixiStage.tsx`)은 2026-08-18 정리에서 삭제 — git 이력에만 존재

**결정 (2026-08-11)**: LLM 호출은 **서버리스 프록시로 전환**한다. 키는 서버 측에만 보관한다. 현재의 `VITE_GEMINI_API_KEY` 클라이언트 직접 호출은 개발 중 임시 상태이며 배포 전 제거 대상이다. 실행 Worker에는 어떤 애플리케이션 secret도 두지 않는다.

**미결정 — 지어내지 말 것**

- 지연 예산(Tracer·Digest·Director·Player·E2E의 P50/P95) 합격 수치 — 스파이크 baseline 실측 후 고정
- interrupt(SharedArrayBuffer + COOP/COEP)가 배포 환경에서 성립하는지
- 이해도 비교 실험의 설계(3조건 between / 2조건 / crossover) — 확보 가능한 표본 수 계산 후 결정
- 가격·라이선스·배포 URL·서비스 운영 형태

## Brand Commitments

- **제품명: TraceLens** (기획안 v3.1에서 확정). ⚠️ [README.md](README.md) 제목만 아직 `Algo-Scope`로 남아 있다 — 드리프트이며 정정 대상
- **태그라인**: "The trace decides what happened; the Director decides what is worth showing."
- **UI 문구는 한국어.** 용어 정의는 [용어해설](docs/superpowers/specs/2026-08-11-algo-scope-glossary.md)을 기준으로 한다
- **시각 언어는 시각화 도구의 카테고리 표준을 따른다** (2026-08-11 확정). 고유한 은유 세계를 짓지 않고, 이 계열이 이미 쓰는 언어를 최고 완성도로 실행한다. 기준선으로 삼는 제품: **Observable · Excalidraw · Python Tutor** — 다이어그램이 주인공이고 크롬은 물러서며, 값은 언제나 모노스페이스로 정확하게. 이 약속은 취향이 아니라 결정이며, 바꾸려면 명시적으로 뒤집어야 한다
- **화면의 레지스터**: 개발자가 신뢰할 밀도로 짓되, 첫 진입과 용어는 학습자 기준으로 쓴다. 둘을 평균 내지 않는다
- **정직성이 제품 목소리다** — 기획 단계에서 반복적으로 못 박은 표현 규칙:
  - 지원하지 않는 것을 지원하는 척하지 않는다 (범위 밖은 벤치마크에서도 제외)
  - "보안 문제를 제거했다"가 아니라 "서버 측 원격 코드 실행 위험과 인프라 비용을 크게 줄인다"
  - 표본이 작으면 "증명했다"가 아니라 "이런 경향을 관찰했다"
  - 근거 없는 숫자를 목표치로 쓰지 않는다

## Evidence on Hand

**있는 것**

- [기술 벤치마크 보고서](docs/superpowers/specs/2026-08-11-benchmark-report.md) — 층화 18샘플(9유형 × 2): 파이프라인 완주율 18/18, Tracer 정확성(기록 stdout ↔ 실제 실행 출력) 18/18, 자막 무결성 18/18, Digest 압축률 평균 53%(38~67%), LLM 대본 검증 통과율 6/6 (Gemini 2.5 Flash, 표본 작음)
- [Slice 1 E2E 체크리스트](docs/superpowers/plans/2026-08-11-e2e-checklist.md) — 매트릭스 시나리오 8/8 통과 (aliasing·루프 접기·IndexError·재귀·무한 루프 clipped·preflight 차단 3종)
- [Tracer 스파이크 보고서](docs/superpowers/specs/2026-08-11-tracer-spike-report.md)
- fixture 20종 — `src/bench/fixtures/` 18개(층화 벤치마크), `src/fixtures/` 2개(aliasing·loop)
- 자동 테스트 — vitest(`src/**/*.test.ts`), 로컬 CPython `tracer_test.py`
- 기획 문서 — [설계 v3.1](docs/superpowers/specs/2026-08-11-algo-scope-design.md), [용어해설](docs/superpowers/specs/2026-08-11-algo-scope-glossary.md), PDF 2종

**없는 것 — 만들어 내면 안 되는 것**

- 실제 사용자·사용 로그·후기·사용자 수
- 이해도 비교 실험 결과, ablation(규칙 무비 vs LLM 무비) 수치
- 브라우저(Pyodide) E2E 지연 실측치 — 벤치마크는 로컬 CPython 트레이스 기준이다
- 외부 인용·수상·기관 검증, 가격·플랜, 배포 URL

## Product Principles

1. **화면은 코드에 대해 거짓말하지 않는다.** 표시되는 값과 순서는 전부 실제 TraceEvent에서만 나온다. 이 원칙과 충돌하는 편의 기능은 채택하지 않는다.
2. **LLM은 품질 계층이지 Core가 아니다.** LLM이 없거나 실패해도 제품은 규칙 기반 대본으로 완주한다.
3. **범위를 정직하게 선언한다.** 못 하는 것은 실행 전에 알려주고, 지원하는 척하지 않는다.
4. **Debugger가 아니라 Movie.** 기본 경험은 자동 재생이고, 탐색은 원할 때 언제든 가능하다.
5. **실행 공간에는 비밀을 두지 않는다.** 우리 사용자는 정의상 이해하지 못한 코드를 실행하러 온다.

## Accessibility & Inclusion

제품 고유 요구는 아직 확립되지 않았다 (**미결정**). 다음 구간 목표가 팀 외부 실사용자이므로 배포 전 최소 기준 — 재생 컨트롤의 키보드 조작, 자막 대비, 모션 감소 선호(`prefers-reduced-motion`) 대응 — 을 정할 필요가 있다.
