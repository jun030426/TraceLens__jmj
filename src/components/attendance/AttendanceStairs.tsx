/**
 * [출석 페이지 전용 컴포넌트] 출석 스탬프 계단 — 출석 1번마다 토끼가 계단 한 칸을 올라가는 애니메이션
 * - 학생 출석 현황 페이지(Attendance)에서 사용
 */

import { useEffect, useRef, useState, type CSSProperties } from 'react'
// 계단을 올라가는 토끼 (가방 메고 달리는 토끼)
import rabbitImg from '../../assets/rabbit-climb.png'
import { MOOD_INFO, type RabbitMood } from '../../utils/rabbitMood'

interface AttendanceStairsProps {
  /** 지금까지 출석한 횟수 = 토끼가 올라갈 계단 수 */
  attended: number
  /** 전체 계단 수 (예: 총 주차) */
  total: number
  /** 다시 처음부터 올라가게 하고 싶을 때 바꿔주는 값 (예: 강의 id) */
  resetKey?: string | number
  /** 다 올라간 뒤 토끼 표정 (연속 출석 3일 → fire, 연속 결석 3일 → sleep, 7일 → cry) */
  mood?: RabbitMood
}

// 한 계단 오르는 데 걸리는 시간(ms) — CSS 의 --hop-ms 와 맞춰주세요
const HOP_MS = 560

/** 단순한 당근 그림 */
function Carrot({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 6c1.5-2.5 1-4.5 1-4.5s1.8 1.2 1.6 3.6C16.6 4 18 5 18 5s-1.6.6-3 2.2"
        fill="#3fae5a"
      />
      <path d="M11.4 6.2C10.5 3.8 8.6 3 8.6 3s.4 2 1.4 3.6" fill="#57c46f" />
      <path
        d="M8.2 8.4c1.9-1.9 5.2-1.9 7.1 0 .8.8.9 2 .3 2.9L9.6 21.4c-.6 1-2.1.9-2.5-.2L5.4 15c-.6-2.3.4-4.9 2.8-6.6z"
        fill="#ff8a1f"
      />
      <path
        d="M8 12.2l2 .8M7.3 15.4l1.8.6M9.8 9.9l1.4.7"
        stroke="#e06a00"
        strokeWidth="1"
        strokeLinecap="round"
      />
    </svg>
  )
}

/**
 * 출석 스탬프 계단
 * - 출석 1번 = 계단 1칸. 토끼가 한 칸씩 올라가며 계단 위 당근을 하나씩 챙겨요.
 * - 화면에 들어올 때마다(또는 resetKey 가 바뀔 때) 처음부터 올라가는 애니메이션이 재생돼요.
 * - '움직임 줄이기' 설정을 켠 사용자에게는 애니메이션 없이 바로 결과를 보여줘요.
 */
export default function AttendanceStairs({
  attended,
  total,
  resetKey,
  mood = 'happy',
}: AttendanceStairsProps) {
  const target = Math.max(0, Math.min(attended, total))
  const reduceMotion =
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  // pos: 토끼가 서 있는 칸 (0 = 출발점, 1~total = 계단)
  const [pos, setPos] = useState(reduceMotion ? target : 0)
  const [run, setRun] = useState(0) // '다시 보기' 용

  useEffect(() => {
    if (reduceMotion) {
      setPos(target)
      return
    }
    setPos(0)
    if (target === 0) return
    let step = 0
    // 처음 한 박자 쉬고 출발
    const timer = window.setInterval(() => {
      step += 1
      setPos(step)
      if (step >= target) window.clearInterval(timer)
    }, HOP_MS)
    return () => window.clearInterval(timer)
  }, [target, resetKey, run, reduceMotion])

  // 좁은 화면(가로 스크롤)에서는 토끼가 항상 보이도록 따라가며 스크롤
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const box = scrollRef.current
    if (!box || box.scrollWidth <= box.clientWidth) return
    const x = ((pos + 0.5) / (total + 1)) * box.scrollWidth - box.clientWidth / 2
    box.scrollTo({ left: Math.max(0, x), behavior: reduceMotion ? 'auto' : 'smooth' })
  }, [pos, total, reduceMotion])

  const climbing = pos < target
  // 올라가는 동안은 기본 토끼, 다 올라가면 상태 토끼로 바뀜
  const showMood = !climbing && mood !== 'happy'
  const rabbitSrc = showMood ? MOOD_INFO[mood].image : rabbitImg
  const columns = total + 1 // 출발점 + 계단

  return (
    <div
      className="stairs"
      style={{ '--cols': columns, '--hop-ms': `${HOP_MS}ms` } as CSSProperties}
    >
      <div className="stairs-top">
        <div className="stairs-count" aria-live="polite">
          <Carrot size={20} />
          <strong>{pos}</strong>
          <span>/ {total}개 모았어요</span>
        </div>
        <button
          type="button"
          className="stairs-replay"
          onClick={() => setRun((n) => n + 1)}
          disabled={climbing || target === 0}
        >
          ↺ 다시 보기
        </button>
      </div>

      <div className="stairs-scroll" ref={scrollRef}>
        <div
          className="stairs-stage"
          role="img"
          aria-label={`출석 ${target}번, 계단 ${total}칸 중 ${target}칸을 올랐어요`}
        >
          {/* 계단 */}
          {Array.from({ length: columns }, (_, k) => {
            const reached = k > 0 && k <= pos
            const isStart = k === 0
            const isGoal = k === total
            return (
              <div
                key={k}
                className={`stairs-step ${isStart ? 'start' : ''} ${reached ? 'reached' : ''} ${
                  k <= target && !isStart ? 'earned' : ''
                } ${isGoal ? 'goal' : ''}`}
                style={{ '--k': k } as CSSProperties}
              >
                {!isStart && (
                  <span
                    className={`stairs-carrot ${reached ? (reduceMotion ? 'gone' : 'collect') : ''} ${
                      k > target ? 'later' : ''
                    }`}
                  >
                    <Carrot />
                  </span>
                )}
                <span className="stairs-label">{isStart ? '출발' : isGoal ? '🏁' : `${k}`}</span>
                {reached && (
                  <span className="stairs-stamp" aria-hidden="true">
                    ✓
                  </span>
                )}
              </div>
            )
          })}

          {/* 토끼 */}
          <div className="stairs-rabbit" style={{ '--p': pos } as CSSProperties}>
            <div
              key={`${run}-${pos}-${showMood ? mood : 'climb'}`}
              className={`stairs-rabbit-hop ${
                showMood ? `mood mood-${mood}` : pos > 0 && !reduceMotion ? 'hop' : ''
              }`}
            >
              <img src={rabbitSrc} alt="" draggable={false} />
              {pos > 0 && (
                <span className="stairs-bag">
                  <Carrot size={14} />
                  {pos}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      <p className="stairs-message">
        {target === 0
          ? '첫 출석을 하면 토끼가 첫 계단을 올라가요!'
          : climbing
            ? '토끼가 당근을 챙기며 올라가는 중…'
            : target >= total
              ? `🎉 ${total}칸 완주! 당근을 모두 모았어요`
              : `출석 ${target}번! 완주까지 ${total - target}칸 남았어요`}
      </p>
    </div>
  )
}
