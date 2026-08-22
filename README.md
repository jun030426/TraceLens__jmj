# TraceLens

**붙여넣기 전에 돌아가는 걸 봅니다 — Python 실행을 영화로 만드는 자동 시각화 도구**

TraceLens는 사용자가 붙여넣은 Python 코드를 브라우저 안에서 실제로 실행하고(Pyodide), 실행이 남긴 트레이스를 **무성영화**로 자동 변환하는 웹 애플리케이션입니다. `visualize()` 같은 보조 함수 없이, 코딩을 아예 안 해본 사람도 흐름 정도는 따라갈 수 있는 것이 합격선입니다.

## 핵심 원칙

- **값·순서는 트레이스에서만.** 자막·비유·연출 어느 층도 실행 사실을 지어내지 않는다. 해석이 안 되면 침묵이 기본값.
- **은유는 스킨, 사실은 트레이스.** 값은 막대 높이로, 비교는 저울로, 반복은 도는 화살로 — 표현은 물체의 언어를 쓰되 수치는 전부 실측.
- **실패해도 빈 화면은 없다.** AI 실패 → 규칙 대본, 특화 뷰 실패 → 일반 뷰, 예외는 실패가 아니라 콘텐츠.

## 파이프라인

```text
Python 코드
→ tracer (Pyodide Web Worker, sys.settrace)   src/trace/
→ TraceEvent[] (localsDelta · objectsDelta)
→ buildStage   캐스팅 — 무대에 올릴 객체·변수·프레임        src/film/
→ choreograph  안무 — 사건을 모션·자막·값 이동으로 번역
→ compose      구성 — 샷마다 누가 어디에 얼마나 크게 (sticky focus·커튼콜)
→ decorate     AI 연출 반영 — 완급·확대·여운 (규칙 폴백 안전)
→ WorldStage   SVG + GSAP 렌더 — 막대·저울·칩·격자·플래시
```

곁가지: `digest → LLM Director(Gemini) → screenplay`가 자막·챕터·연출 동사를 보태고, 실패하면 규칙 대본이 그대로 재생됩니다 (`src/screenplay/`, `src/director/`).

## 화면

| 경로 | 내용 |
|---|---|
| `/` | 랜딩 — 라이브 트레이스 다이어그램 데모 |
| `/app` | 본편 — 에디터 · 실행 · 필름 재생 · 자막 · 인스펙터 |
| `/help` `/settings` `/about` | 지원 범위 · 설정(배속·모션 감소·실행 상한) · 소개 |

이해도 검증은 **라이브 사용 평가**로 진행한다 — 참가자가 주어진 낯선 코드를 `/app`에서 직접 실행해 보고 transfer 질문(입력을 바꾸면 결과 예측)에 답하는 방식. 상세 설계는 실행 직전에 확정한다 (설계서 8절).

## 은유 스킨 (현재 방향, 2026-08-18)

- **값 막대**: 음수 없는 숫자 리스트는 칸마다 값 비례 막대 — 정렬이 "계단이 되는 모양"으로 보인다
- **비교 저울**: 양팔에 값 카드가 올라가 무거운 쪽으로 기울고 참/거짓 도장 — 비교가 이어지는 동안 무대에 머문다
- **값 이동 칩**: `x = arr[i]`·`append`·`pop`에서 값이 실제로 날아간다 (소스 라인 접지)
- **색 4역할 계약**: 읽기=파랑 · 쓰기=호박 · 참/완성=초록 · 거짓/오류=빨강 (`src/ui/app.css`)
- 정렬이 실제로 완성됐을 때만 초록 스윕, 테마 감지(`src/film/theme.ts`)는 불확실하면 중립 폴백

## 개발

```bash
npm install
npm run dev     # Vite 개발 서버
npm test        # vitest (필름·트레이스·대본 회귀 235+)
npm run build   # tsc + vite build
npm run lint    # oxlint
```

- AI 연출을 쓰려면 `.env.example`을 참고해 `VITE_GEMINI_API_KEY`를 설정 (없으면 규칙 연출로 동작)
- 테스트 fixture 재생성: `scripts/gen_fixtures.py` · `gen_film_fixture.py` · `gen_bench_traces.py` (로컬 CPython으로 tracer를 돌려 JSON 생성)
- LLM 통과율 실측: `RUN_LLM_BENCH=1 npx vitest run src/bench/llmPass.bench.test.ts`

## 문서

- [PRODUCT.md](PRODUCT.md) — 제품 계약·지원 범위·구조적 제약 (spanRef, 관측 귀속 규칙 등)
- [DESIGN.md](DESIGN.md) — 디자인 시스템 (토큰·표면·금칙)
- `docs/superpowers/specs/` — 살아있는 설계 문서 (기획 동결본, 은유 스킨 설계, 파일럿 가이드, 실측 보고서)
- `docs/superpowers/plans/` — 진행 중 계획 (실행 완료된 계획은 `archive/`로 내려간다)
