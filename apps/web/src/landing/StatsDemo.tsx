/**
 * [랜딩 그림] 스크롤 스토리 '분석' 단계 — 학생용 학습 분석 화면의 미리보기 (예시 데이터)
 *   자주 틀리는 개념 · 약한 챕터 · 문제 유형별 정답률
 * - 막대가 천천히 오르내리고 퍼센트 숫자도 같이 바뀌어요 (보기 좋게 하려는 움직임이고 실제 기록은 아니에요).
 * - '움직임 줄이기' 설정이면 멈춘 값으로 보여줘요.
 * - 스타일: styles/landing.css 의 .v-sd-*
 */

import { useEffect, useState } from 'react'
import DemoFit from './DemoFit'

// base = 가운데 값(%), swing = 오르내리는 폭
// [임시 데이터] 랜딩 소개용 분석 수치 — 가운데 값(base)과 오르내리는 폭(swing)을 정해 둔 것 (실제 기록 아님)
const GROUPS = [
  {
    title: '다시 살펴볼 개념',
    note: '오답률',
    tone: 'bad',
    rows: [
      { name: '재귀', base: 62, swing: 9 },
      { name: '퀵 정렬 피벗', base: 51, swing: 8 },
      { name: '연결 리스트 삽입', base: 43, swing: 7 },
      { name: '시간 복잡도', base: 34, swing: 6 },
    ],
  },
  {
    title: '주차별 이해도',
    note: '정답률',
    tone: 'mid',
    rows: [
      { name: '4주차 재귀와 분할 정복', base: 38, swing: 8 },
      { name: '5주차 정렬 알고리즘', base: 49, swing: 9 },
      { name: '2주차 연결 리스트', base: 61, swing: 7 },
      { name: '3주차 스택과 큐', base: 77, swing: 6 },
    ],
  },
  {
    title: '학습 유형별 정답률',
    note: '정답률',
    tone: 'good',
    rows: [
      { name: '오늘의 이론', base: 81, swing: 6 },
      { name: '복습 퀴즈', base: 66, swing: 8 },
      { name: '시험 대비 서술형', base: 47, swing: 9 },
      { name: '오늘의 실습', base: 58, swing: 10 },
    ],
  },
]

export default function StatsDemo() {
  const [time, setTime] = useState(0)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let frame = 0
    const start = performance.now()
    const tick = (nowMs: number) => {
      setTime((nowMs - start) / 1000)
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [])

  return (
    <DemoFit width={1000}>
      <div className="v-sd" aria-hidden="true">
        <div className="v-sd-head">
          <strong>학습 기록</strong>
          <span>예시 데이터 · 로그인하면 내 기록으로 보여요</span>
        </div>
        <div className="v-sd-grid">
          {GROUPS.map((g, gi) => (
            <div key={g.title} className={`v-sd-box ${g.tone}`}>
              <div className="v-sd-box-head">
                <strong>{g.title}</strong>
                <span>{g.note}</span>
              </div>
              {g.rows.map((r, ri) => {
                // 막대마다 박자를 조금씩 다르게
                const value = Math.round(r.base + r.swing * Math.sin(time * (0.9 + ri * 0.17) + gi * 1.3 + ri * 0.8))
                return (
                  <div key={r.name} className="v-sd-row">
                    <span>{r.name}</span>
                    <i>
                      <b style={{ width: `${value}%` }} />
                    </i>
                    <em>{value}%</em>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
        <p className="v-sd-foot">다시 살펴볼 개념은 퀴즈와 복습으로 이어갈 수 있어요.</p>
      </div>
    </DemoFit>
  )
}
