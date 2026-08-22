import type { LlmCallFn } from './llmDirector'

// 개발용 직접 호출 어댑터. 키는 .env.local(VITE_GEMINI_API_KEY)에만 두고 절대 커밋하지 않는다.
// 배포 시에는 이 어댑터 대신 서버리스 프록시를 거친다 (기획안 §3 — 키는 서버 측에만).
/** 캐시 키의 modelVersion 조각 — 모델이 바뀌면 저장된 연출도 무효가 되어야 한다 */
export const GEMINI_MODEL = 'gemini-2.5-flash'

export function makeGeminiCall(apiKey: string, model = GEMINI_MODEL): LlmCallFn {
  return async (prompt: string) => {
    // 매달린 요청이 폴백을 영원히 막지 않게 — 20초면 실패로 친다
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 20000)
    try {
      const res = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-goog-api-key': apiKey },
          signal: ctrl.signal,
          body: JSON.stringify({
            contents: [{ parts: [{ text: prompt }] }],
            generationConfig: {
              responseMimeType: 'application/json',
              temperature: 0.4,
              // 연출 선택은 구조화 JSON 과제 — 2.5 계열의 기본 thinking은 지연만 키운다
              thinkingConfig: { thinkingBudget: 0 },
            },
          }),
        },
      )
      if (!res.ok) throw new Error(`Gemini API ${res.status}: ${(await res.text()).slice(0, 200)}`)
      const data = await res.json()
      const text = data?.candidates?.[0]?.content?.parts?.[0]?.text
      if (typeof text !== 'string') throw new Error('Gemini 응답에 텍스트가 없습니다')
      return text
    } finally {
      clearTimeout(timer)
    }
  }
}

export const geminiApiKey = (import.meta.env.VITE_GEMINI_API_KEY as string | undefined)?.trim() || undefined
