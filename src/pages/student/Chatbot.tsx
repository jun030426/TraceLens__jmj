/**
 * [학생 AI 챗봇 페이지] 주소: /ai  (헤더 메뉴 '챗봇')
 * - 왼쪽에서 수강 중인 강의를 고르면 그 강의에 대한 대화가 따로 저장돼요 (화면에만, 새로고침하면 사라짐)
 * - 답변은 api/chatApi.ts 의 sendChatMessage 에서 받아요 (지금은 임시 답변)
 *   실제로는 프론트 → 우리 백엔드(/api/chat) → 우리 AI 서버 순서로 전달돼요. (외부 AI API key 를 쓰지 않음)
 */

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import PageLayout from '../../components/layout/PageLayout'
import { useStudentNo } from '../../hooks/useAuth'
import { myCoursesOf, useCourseStore } from '../../store/courseStore'
import { accentStyle } from '../../utils/course'
import { sendChatMessage, type ChatMessage } from '../../api/chatApi'

// 강의를 고르지 않았을 때(일반 질문) 대화 키
const GENERAL = 'general'

const SUGGESTIONS = [
  '이번 주 수업 내용을 요약해줘',
  '헷갈리는 개념을 쉽게 설명해줘',
  '시험 대비 핵심 개념을 정리해줘',
  '연습 문제를 3개 만들어줘',
]

const newId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

export default function Chatbot() {
  const db = useCourseStore()
  const myCourses = myCoursesOf(db, useStudentNo()).map((x) => x.course)

  const [courseKey, setCourseKey] = useState<string>(GENERAL)
  const [threads, setThreads] = useState<Record<string, ChatMessage[]>>({})
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const currentCourse = myCourses.find((c) => String(c.id) === courseKey) ?? null
  const messages = threads[courseKey] ?? []

  // 새 메시지가 오면 맨 아래로 스크롤
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, sending])

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || sending) return

    const key = courseKey
    const userMsg: ChatMessage = { id: newId(), role: 'user', content, createdAt: Date.now() }
    const history = [...(threads[key] ?? []), userMsg]
    setThreads((prev) => ({ ...prev, [key]: history }))
    setInput('')
    setSending(true)

    let reply: ChatMessage
    try {
      const answer = await sendChatMessage({
        courseId: key === GENERAL ? null : Number(key),
        messages: history.map(({ role, content }) => ({ role, content })),
      })
      reply = { id: newId(), role: 'assistant', content: answer, createdAt: Date.now() }
    } catch {
      reply = {
        id: newId(),
        role: 'assistant',
        content: '답변을 받지 못했어요. 잠시 후 다시 시도해 주세요.',
        createdAt: Date.now(),
        error: true,
      }
    }
    setThreads((prev) => ({ ...prev, [key]: [...(prev[key] ?? []), reply] }))
    setSending(false)
    inputRef.current?.focus()
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    send(input)
  }

  // Enter = 보내기, Shift+Enter = 줄바꿈 (한글 조합 중에는 보내지 않음)
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send(input)
    }
  }

  const resetThread = () => {
    setThreads((prev) => ({ ...prev, [courseKey]: [] }))
    inputRef.current?.focus()
  }

  const selectCourse = (key: string) => {
    if (sending) return
    setCourseKey(key)
    setInput('')
  }

  return (
    <PageLayout role="student" active="chatbot" className="chat-page" mainClassName="chat-main">
      {/* 왼쪽: 강의 선택 */}
      <aside className="chat-side" aria-label="질문할 강의">
        <p className="chat-side-title">질문할 강의</p>
        <button
          type="button"
          className={`chat-course ${courseKey === GENERAL ? 'active' : ''}`}
          onClick={() => selectCourse(GENERAL)}
        >
          <span className="chat-course-icon general">✦</span>
          <span className="chat-course-name">일반 질문</span>
          {(threads[GENERAL]?.length ?? 0) > 0 && <i className="chat-dot" />}
        </button>

        {myCourses.map((c) => (
          <button
            key={c.id}
            type="button"
            className={`chat-course course-card-${c.color} ${courseKey === String(c.id) ? 'active' : ''}`}
            style={accentStyle(c)}
            onClick={() => selectCourse(String(c.id))}
          >
            <span className="chat-course-icon">{c.title.charAt(0)}</span>
            <span className="chat-course-name">{c.title}</span>
            {(threads[String(c.id)]?.length ?? 0) > 0 && <i className="chat-dot" />}
          </button>
        ))}

        {myCourses.length === 0 && (
          <p className="chat-side-empty">
            수강 중인 강의가 없어요. 강의를 신청하면 강의별로 질문할 수 있어요.
          </p>
        )}
      </aside>

      {/* 오른쪽: 대화 */}
      <section className="chat-panel" aria-label="AI 챗봇 대화">
        <div className="chat-panel-head">
          <div>
            <strong>{currentCourse ? currentCourse.title : '일반 질문'}</strong>
            {currentCourse && <span>이 강의 자료를 바탕으로 답변해요</span>}
          </div>
          {messages.length > 0 && (
            <button type="button" className="chat-reset" onClick={resetThread}>
              새 대화
            </button>
          )}
        </div>

        <div className="chat-messages" ref={listRef}>
          {messages.length === 0 ? (
            <div className="chat-empty">
              <div className="chat-empty-icon">✦</div>
              <h2>무엇이든 물어보세요</h2>
              <p>
                {currentCourse
                  ? `‘${currentCourse.title}’ 수업에 대해 궁금한 점을 질문해 보세요.`
                  : '공부하다 막히는 부분을 편하게 물어보세요.'}
              </p>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((q) => (
                  <button key={q} type="button" onClick={() => send(q)}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <ul>
              {messages.map((m) => (
                <li key={m.id} className={`chat-msg ${m.role} ${m.error ? 'error' : ''}`}>
                  {m.role === 'assistant' && (
                    <span className="chat-avatar" aria-hidden="true">
                      ✦
                    </span>
                  )}
                  <div className="chat-bubble">{m.content}</div>
                </li>
              ))}
              {sending && (
                <li className="chat-msg assistant">
                  <span className="chat-avatar" aria-hidden="true">
                    ✦
                  </span>
                  <div className="chat-bubble chat-typing" aria-label="답변 작성 중">
                    <i />
                    <i />
                    <i />
                  </div>
                </li>
              )}
            </ul>
          )}
        </div>

        <form className="chat-input" onSubmit={handleSubmit}>
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="질문을 입력하세요 (Shift + Enter 줄바꿈)"
            aria-label="질문 입력"
          />
          <button type="submit" disabled={!input.trim() || sending}>
            보내기
          </button>
        </form>
      </section>
    </PageLayout>
  )
}
