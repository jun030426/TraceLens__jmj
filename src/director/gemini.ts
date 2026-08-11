import type { LlmCallFn } from './llmDirector'

// 개발용 직접 호출 어댑터. 키는 .env.local(VITE_GEMINI_API_KEY)에만 두고 절대 커밋하지 않는다.
// 배포 시에는 이 어댑터 대신 서버리스 프록시를 거친다 (기획안 §3 — 키는 서버 측에만).
export function makeGeminiCall(apiKey: string, model = 'gemini-2.5-flash'): LlmCallFn {
  return async (prompt: string) => {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-goog-api-key': apiKey },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: { responseMimeType: 'application/json', temperature: 0.4 },
        }),
      },
    )
    if (!res.ok) throw new Error(`Gemini API ${res.status}: ${(await res.text()).slice(0, 200)}`)
    const data = await res.json()
    const text = data?.candidates?.[0]?.content?.parts?.[0]?.text
    if (typeof text !== 'string') throw new Error('Gemini 응답에 텍스트가 없습니다')
    return text
  }
}

export const geminiApiKey = (import.meta.env.VITE_GEMINI_API_KEY as string | undefined)?.trim() || undefined
