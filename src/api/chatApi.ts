/**
 * [서버 연결] AI 챗봇 API — 학생 챗봇 페이지(pages/student/Chatbot.tsx)에서 사용
 *
 * 흐름: 프론트 → POST /api/chat (우리 백엔드) → 백엔드가 우리 AI 서버(직접 띄운 모델)에 질문 전달 → 답변 반환
 *  - 프론트는 AI 서버를 직접 부르지 않고, API key 도 쓰지 않아요. (api/client.ts 맨 위 설명 참고)
 *  - courseId 가 있으면 백엔드가 그 강의의 강의자료(교수자가 올린 파일)를 찾아서
 *    AI 서버에 함께 넘겨 주면 '강의 자료 기반 답변'이 돼요. (예: 자료 검색 후 프롬프트에 포함)
 *  - 로그인한 학생이 누구인지는 백엔드가 세션 쿠키로 알아요 → 수강 중인 강의인지 서버에서 확인해 주세요.
 *
 * 요청/응답 약속 (백엔드 담당자와 맞출 부분)
 *   POST /api/chat
 *   요청: { courseId: number | null, messages: [{ role: 'user' | 'assistant', content: string }] }
 *         messages 는 지금까지의 대화 전체, 마지막이 이번 질문 (AI 가 앞 대화 맥락을 알 수 있게)
 *   응답: { reply: string }
 *
 * 지금은 VITE_USE_MOCK 이 true 라서 '임시 답변'을 돌려줘요. 서버가 준비되면 .env 에서 false 로 바꾸세요.
 * (나중에 답변이 길어 느리면 스트리밍(SSE)으로 바꾸는 것도 고려 — 그때는 이 함수만 바꾸면 돼요)
 */

import { apiFetch, mockDelay, USE_MOCK } from './client'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
  /** 답변을 받지 못했을 때 */
  error?: boolean
}

export interface SendChatParams {
  /** 질문할 강의 (null = 강의 상관없이 일반 질문) — 강의 자료 기반 답변에 사용 */
  courseId: number | null
  /** 지금까지의 대화 (마지막이 이번 질문) */
  messages: Pick<ChatMessage, 'role' | 'content'>[]
}

/** 질문을 보내고 답변 텍스트를 받아요 */
export async function sendChatMessage(params: SendChatParams): Promise<string> {
  if (USE_MOCK) {
    // 임시 답변 (실제 AI 아님)
    const last = params.messages[params.messages.length - 1]?.content ?? ''
    return mockDelay(
      `아직 AI 서버와 연결되지 않아 임시 답변을 보여드려요.\n\n받은 질문: “${last}”`,
      700,
    )
  }

  const data = await apiFetch<{ reply: string }>('/chat', { method: 'POST', body: params })
  return data.reply
}
