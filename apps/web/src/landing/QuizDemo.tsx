/**
 * [랜딩 그림] '이론' 단계 데모 — 오늘의 퀴즈 한 문제 (학생용 퀴즈 풀이 화면의 미리보기)
 * - 스크롤(progress 0~1)에 따라 가짜 마우스 커서가 '힌트 보기'를 눌러 힌트가 1 → 2 → 3단계로 쌓여요.
 * - 보기 고르기 · 정답 확인 · 새 퀴즈 생성은 방문자가 직접 눌러 볼 수 있어요 (예시 문제 3개가 돌아가며 나와요).
 * - 상자 크기: 힌트 3개가 다 열렸을 때의 높이를 기준으로 배율을 한 번만 정해요.
 *   그래서 힌트가 열려도 가로 폭은 그대로이고 아래로만 길어져요. (힌트 3개를 숨겨서 미리 그려 두고 그 높이를 재요)
 * - 스타일: styles/landing.css 의 .v-quiz-* · .v-cv-*
 */

import { useLayoutEffect, useRef, useState } from 'react'
import { IconArrowUpRight, IconDoc } from './Icons'

// 랜딩에서 체험하는 예시 문제. 실제 퀴즈 생성은 학생 퀴즈 화면에서 제공해요.
// [임시 데이터] 랜딩 소개용 예시 문제 3개 (문제 은행과 연결되지 않아요)
const QUESTIONS = [
  {
    text: '배열에서 인덱스로 원소 하나에 접근할 때 시간 복잡도는?',
    choices: ['O(1)', 'O(n)', 'O(n log n)', 'O(n²)'], answer: 0,
    hints: ['배열의 원소는 메모리에 연속해서 저장돼요.', '시작 주소와 인덱스로 원하는 원소의 위치를 바로 계산해요.', '배열의 길이가 늘어나도 접근에 필요한 연산 수는 일정해요.'],
    explanation: '배열의 시작 주소에 인덱스 × 원소 크기를 더하면 위치를 바로 찾을 수 있어요. 배열 길이와 무관하게 일정한 시간이 걸리므로 O(1)이에요.',
  },
  {
    text: '길이가 n인 배열의 모든 원소를 한 번씩 확인할 때 시간 복잡도는?',
    choices: ['O(1)', 'O(log n)', 'O(n)', 'O(n²)'], answer: 2,
    hints: ['배열의 원소를 몇 번 확인하는지 생각해 보세요.', '원소가 10개면 10번, 100개면 100번 확인해요.', '필요한 연산 수가 배열의 길이 n에 비례해요.'],
    explanation: 'n개의 원소를 각각 한 번씩 확인하므로 총 n번의 연산이 필요해요. 따라서 시간 복잡도는 O(n)이에요.',
  },
  {
    text: '정렬되지 않은 배열에서 최댓값을 찾는 시간 복잡도는?',
    choices: ['O(log n)', 'O(n²)', 'O(1)', 'O(n)'], answer: 3,
    hints: ['최댓값이 어느 위치에 있는지 미리 알 수 있을까요?', '현재까지의 최댓값과 다음 원소를 차례로 비교해요.', '모든 원소를 한 번씩 확인하면 최댓값을 찾을 수 있어요.'],
    explanation: '최댓값을 확실히 찾으려면 모든 원소를 확인해야 해요. 한 번의 순회로 찾을 수 있으므로 시간 복잡도는 O(n)이에요.',
  },
]

export default function QuizDemo({ progress }: { progress: number }) {
  // 스크롤을 8개 장면으로: 0 시작 · 1 커서 이동 · 2 누름(힌트 1) · 3 · 4 누름(힌트 2) · 5 · 6 누름(힌트 3) · 7
  const phase = Math.min(7, Math.floor(Math.max(0, progress) * 8))
  const hintLevel = Math.max(0, Math.min(3, Math.floor((phase - 1) / 2)))
  const rootRef = useRef<HTMLDivElement>(null)
  const hintRef = useRef<HTMLButtonElement>(null)
  const cursorRef = useRef<HTMLSpanElement>(null)
  const feedbackRef = useRef<HTMLDivElement>(null)
  // 힌트 3개가 다 열렸을 때의 높이를 미리 재는 숨은 복사본
  const fullHintsRef = useRef<HTMLDivElement>(null)
  const [questionIndex, setQuestionIndex] = useState(0)
  const [choice, setChoice] = useState<number | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const question = QUESTIONS[questionIndex]

  const newQuiz = () => {
    setQuestionIndex(index => (index + 1) % QUESTIONS.length)
    setChoice(null)
    setSubmitted(false)
  }

  useLayoutEffect(() => {
    const root = rootRef.current
    const hint = hintRef.current
    const cursor = cursorRef.current
    if (!root || !hint || !cursor) return
    const place = () => {
      const canvas = root.parentElement
      if (canvas) {
        const styles = getComputedStyle(canvas)
        const available = canvas.clientHeight - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom)
        // 힌트가 다 열렸을 때 높이를 기준으로 배율을 한 번만 정해요 → 힌트를 열어도 상자 가로 폭은 그대로, 아래로만 길어져요
        const shownHints = feedbackRef.current?.offsetHeight ?? 0
        const fullHints = Math.max(shownHints, fullHintsRef.current?.offsetHeight ?? 0)
        const fullHeight = root.offsetHeight - shownHints + fullHints
        root.style.transform = `scale(${Math.min(1, Math.max(0.1, available / fullHeight))})`
        root.style.transformOrigin = 'top center'
      }
      const box = root.getBoundingClientRect()
      const target = hint.getBoundingClientRect()
      const x = phase === 0 ? root.offsetWidth * .85 : (target.left - box.left + target.width / 2) * root.offsetWidth / box.width
      const y = phase === 0 ? 50 : (target.top - box.top + target.height / 2) * root.offsetHeight / box.height
      cursor.style.transform = `translate(${x}px, ${y}px)`
    }
    // 힌트가 쌓이면서 박스가 축소되거나 버튼이 이동해도 커서 끝을 계속 맞춰요.
    let frame = 0
    const track = () => {
      place()
      frame = requestAnimationFrame(track)
    }
    track()
    return () => cancelAnimationFrame(frame)
  }, [phase, submitted])

  return <div ref={rootRef} className="v-quiz-demo">
    <div className="v-cv v-cv-quiz">
    <div className="v-quiz-heading"><span className="v-cv-tag">오늘의 이론 · 1주차 배열과 복잡도</span><span>미리보기</span></div>
    <strong>{question.text}</strong>
    <div className="v-quiz-choices" role="group" aria-label="퀴즈 답안 선택">
      {question.choices.map((text, index) => <button key={text}
        className={`v-cv-choice ${choice === index ? 'on' : ''} ${submitted && index === question.answer ? 'correct' : ''}`}
        aria-pressed={choice === index} disabled={submitted} onClick={() => setChoice(index)}>
        <span>{['①', '②', '③', '④'][index]}</span>{text}
      </button>)}
    </div>
    <div className="v-quiz-actions">
      <button ref={hintRef} className={`v-quiz-hint-button ${[2, 4, 6].includes(phase) ? 'press' : ''}`}
        aria-disabled="true" tabIndex={-1}>
        {hintLevel < 3 ? <><IconDoc /> 자료 근거 보기</> : '자료 근거를 모두 확인했어요'}
      </button>
      <button className="v-quiz-submit" disabled={choice === null || submitted} onClick={() => setSubmitted(true)}>정답 확인</button>
    </div>
    <div className="v-quiz-feedback-wrap">
    <div ref={fullHintsRef} className="v-quiz-feedback measure" aria-hidden="true">
      {question.hints.map((hint, index) => <div key={hint} className="v-cv-hint"><b>근거 {index + 1}</b><span>{hint}</span></div>)}
    </div>
    <div ref={feedbackRef} className="v-quiz-feedback" aria-live="polite">
      {question.hints.slice(0, hintLevel).map((hint, index) => <div key={hint} className="v-cv-hint"><b>근거 {index + 1}</b><span>{hint}</span></div>)}
      {submitted && <div className="v-quiz-answer"><b>{choice === question.answer ? '정답이에요!' : '정답을 확인해 보세요.'} · {question.choices[question.answer]}</b><p>{question.explanation}</p></div>}
    </div>
    </div>
    </div>
    <div className="v-quiz-footer"><span>오늘의 4문항을 마치면</span><button onClick={newQuiz}>추가 학습 이어가기 <IconArrowUpRight /></button></div>
    <span ref={cursorRef} aria-hidden="true" className={`v-md-cursor ${[2, 4, 6].includes(phase) ? 'press' : ''}`}>
      <svg width="33" height="33" viewBox="0 0 44 44"><path d="M40 4 L4 19 L19 25 L25 40 Z" fill="none" stroke="#fff" strokeWidth="3.2" strokeLinejoin="round" /></svg><i />
    </span>
  </div>
}
