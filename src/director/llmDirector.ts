import type { Digest } from '../digest/buildDigest'
import type { Screenplay } from '../screenplay/types'
import { resolveScreenplay, salvageScreenplay } from './resolver'

export type LlmCallFn = (prompt: string) => Promise<string>

const buildPrompt = (code: string, digest: Digest) => `당신은 프로그램 실행 기록을 학습자용 애니메이션으로 연출하는 감독입니다.

## 소스 코드
\`\`\`python
${code}
\`\`\`

## 실행 요약 (Digest)
각 스팬은 실제 실행 기록의 한 구간입니다. 당신은 이 spanId만 참조할 수 있습니다.
iterations는 그 반복 구간이 실제로 돈 총 횟수입니다 — 반복 횟수를 언급할 땐 이 숫자만 사용하세요 (재생기가 자동으로 "(총 N회 반복)"을 덧붙이므로 narration에 횟수를 직접 쓰지 않아도 됩니다).
${JSON.stringify(digest.spans)}
${digest.aliasNote ? `\n참고 — 별칭 관계: ${digest.aliasNote}` : ''}

## 출력 형식 (JSON만, 다른 텍스트 금지)
{"chapters":[{"title":"챕터 제목","scenes":[{"spanRef":"스팬ID","primitive":"variables|callStack|sequence|objectGraph|generic","focus":["변수명"],"pacing":"slow|normal|fast","narration":{"template":"관찰형 한 문장, 값은 {키}로","bindings":{"키":{"name":"변수명"}}}}]}]}

## 연출 규칙 (어기면 거부됨)
1. spanRef는 위 Digest에 있는 spanId만. 실행 순서(sourceSeqRange 오름차순)대로만 배열.
2. {키}는 그 변수의 **값**이 통째로 들어갈 자리다. **변수 이름은 템플릿에 문자 그대로** 쓴다.
   - 나쁨: "변수 {x}을 통해 리스트가 변경됩니다" → {x}가 값으로 치환되어 "변수 [1, 2]을 통해…"가 됨
   - 좋음: "team_b를 통해 추가하면 team_a도 바뀝니다" (이름은 리터럴, 값 불필요)
   - 좋음: "total이 {v}이(가) 됩니다" + bindings {"v":{"name":"total"}} (값이 필요할 때만)
3. 값·숫자를 template에 직접 쓰지 말 것 — 반드시 {키} + bindings로. 값이 필요 없으면 바인딩 생략.
4. narration은 관찰형(무슨 일이 일어나는지)으로 짧게, 조사가 자연스러운 완전한 문장으로. 해석·의도 추측은 챕터 title에만.
5. 별칭 관계가 있으면 그 장면은 primitive를 objectGraph로, pacing을 slow로.
6. 중요한 순간(별칭 생성, 예외, 결과 출력)은 slow, 반복(iterations 있는 스팬)은 fast.
7. 마지막 장면은 프로그램의 최종 상태가 보이도록 variables 또는 objectGraph를 사용할 것 (callStack 금지).
8. 챕터는 2~4개, 학습자가 이해할 이야기 단위로 나눌 것. 모든 스팬을 쓸 필요는 없지만 순서는 지킬 것.
9. 한국어로 작성.`

const stripFences = (s: string) => {
  const m = s.match(/```(?:json)?\s*([\s\S]*?)\s*```/)
  return (m ? m[1] : s).trim()
}

export async function generateScreenplay(code: string, digest: Digest, call: LlmCallFn): Promise<Screenplay> {
  const prompt = buildPrompt(code, digest)
  let lastError = ''
  for (let attempt = 0; attempt < 2; attempt++) {
    const ask = attempt === 0
      ? prompt
      : `${prompt}\n\n## 이전 시도 오류 (수정해서 다시)\n${lastError}`
    const text = await call(ask)
    try {
      return resolveScreenplay(JSON.parse(stripFences(text)), digest)
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err)
    }
  }
  throw new Error(`대본 생성 실패: ${lastError}`)
}

export type DirectedResult = { screenplay: Screenplay; mode: 'ai' | 'ai-partial' }

// 엄격 2회 시도 → 실패하면 마지막 응답에서 유효한 장면만 건져 규칙 장면으로 충전.
// 그것도 안 되면 throw — 호출부가 전체 규칙 폴백으로 내려간다.
export async function generateScreenplayWithSalvage(
  code: string,
  digest: Digest,
  call: LlmCallFn,
  rule: Screenplay,
): Promise<DirectedResult> {
  const prompt = buildPrompt(code, digest)
  let lastError = ''
  let lastText = ''
  for (let attempt = 0; attempt < 2; attempt++) {
    const ask = attempt === 0
      ? prompt
      : `${prompt}\n\n## 이전 시도 오류 (수정해서 다시)\n${lastError}`
    const text = await call(ask)
    lastText = text
    try {
      return { screenplay: resolveScreenplay(JSON.parse(stripFences(text)), digest), mode: 'ai' }
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err)
    }
  }
  try {
    const salvaged = salvageScreenplay(JSON.parse(stripFences(lastText)), digest, rule)
    if (salvaged) return { screenplay: salvaged, mode: 'ai-partial' }
  } catch {
    /* JSON 자체가 깨짐 — 아래 throw로 규칙 폴백 */
  }
  throw new Error(`대본 생성 실패: ${lastError}`)
}
