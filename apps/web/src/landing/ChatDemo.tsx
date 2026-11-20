/**
 * [랜딩 그림] 스크롤 스토리 '챗봇' 단계 — AI 교수님(교수자가 올린 강의 데이터를 아는)에게 물어보는 소통창 미리보기
 *   ① 푼 퀴즈에서 '왜 틀렸나요?' → 문제 맥락 그대로 질문
 *   ② 강의 영상을 보다가 / 퀴즈를 풀고 나서 궁금한 점 질문
 * - 스크롤(progress 0~1)에 따라 대화가 한 줄씩 나와요. AI 답변은 '입력 중' 점 세 개 뒤에 한 글자씩 적혀요.
 *   답변은 예시 글이에요 (실제 답변은 AI 서버가 만들어요).
 * - 대화 칸 높이는 고정이라 답변이 나와도 상자 크기가 바뀌지 않아요.
 * - 스타일: styles/landing.css 의 .v-cd-*
 */

import { useEffect, useRef } from 'react'
import DemoFit from './DemoFit'
import ProfessorPhoto from './ProfessorPhoto'
const PROFESSOR = { name: 'AI 질문' }

// at = 이 말풍선이 나오기 시작하는 스크롤 위치 (AI 답변은 at 부터 TYPE_SPAN 동안 한 글자씩 적혀요)
// [임시 데이터] 랜딩 소개용 대화 — 질문과 답변 모두 미리 적어 둔 글 (AI 답변 아님)
const TALK = [
  { at: 0.04, who: 'me', from: '이론 퀴즈 결과에서', text: '왜 이 답이 틀렸나요?' },
  {
    at: 0.16,
    who: 'ai',
    text: '배열은 원소가 메모리에 나란히 놓여 있어서, 시작 주소에 인덱스만 더하면 위치를 바로 계산할 수 있어요. 처음부터 하나씩 찾아가는 게 아니라서 O(n) 이 아니라 O(1) 이에요.',
    source: '1주차 강의 자료 · 배열과 복잡도',
  },
  { at: 0.5, who: 'me', from: 'AI 강의를 보다가', text: '그럼 연결 리스트는 왜 k번째 원소를 바로 못 찾나요?' },
  {
    at: 0.62,
    who: 'ai',
    text: '연결 리스트는 노드가 흩어져 있고 다음 노드의 주소만 알고 있어요. 그래서 k번째까지 앞에서부터 따라가야 해서 O(n) 이 걸려요. 2주차 AI 강의 ‘노드와 포인터’에서 그림으로 다시 볼 수 있어요.',
    source: '2주차 강의 자료 · 연결 리스트',
  },
] as const
const TYPE_SPAN = 0.24
// 답변이 나오기 전 '입력 중' 점이 보이는 구간
const THINK_SPAN = 0.07

export default function ChatDemo({ progress }: { progress: number }) {
  const p = Math.min(1, Math.max(0, progress))
  const shown = TALK.filter((t) => p >= t.at)
  const next = TALK[shown.length]
  const thinking = next?.who === 'ai' && p >= next.at - THINK_SPAN
  const talkRef = useRef<HTMLDivElement>(null)

  // 대화가 칸보다 길어지면 최신 말풍선이 보이게 아래로
  useEffect(() => {
    const talk = talkRef.current
    if (talk) talk.scrollTop = talk.scrollHeight
  }, [p])

  return (
    <DemoFit width={760}>
      <div className="v-cd" aria-hidden="true">
        <div className="v-cd-head">
          <ProfessorPhoto size={44} />
          <span>
            <b>{PROFESSOR.name}</b>
            <em>강의 자료의 근거와 함께 답해요 · 자료구조</em>
          </span>
        </div>

        <div className="v-cd-context">
          <span>질문에 함께 보내는 문제</span>
          <strong>배열에서 인덱스로 원소 하나에 접근할 때 시간 복잡도는?</strong>
          <p>
            내 답 <b className="bad">O(n)</b> · 정답 <b className="good">O(1)</b>
          </p>
        </div>

        <div className="v-cd-talk" ref={talkRef}>
          {shown.map((t) => {
            // AI 답변은 스크롤에 맞춰 한 글자씩
            const typed = t.who === 'ai' ? Math.min(1, (p - t.at) / TYPE_SPAN) : 1
            const text = t.text.slice(0, Math.max(1, Math.round(t.text.length * typed)))
            return (
              <div key={t.at} className={`v-cd-msg ${t.who}`}>
                {'from' in t && <small>{t.from}</small>}
                <p>
                  {text}
                  {typed < 1 && <i className="v-cd-caret" />}
                </p>
                {'source' in t && typed >= 1 && <span className="v-cd-source">근거 · {t.source}</span>}
              </div>
            )
          })}
          {thinking && (
            <div className="v-cd-msg ai dots">
              <i />
              <i />
              <i />
            </div>
          )}
        </div>

        <div className="v-cd-input">
          <span>궁금한 것을 물어보세요</span>
          <b>보내기</b>
        </div>
      </div>
    </DemoFit>
  )
}
