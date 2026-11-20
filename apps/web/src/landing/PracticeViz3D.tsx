/**
 * [하루의 학습 · 실습] 시각화 그림을 입체로 — PracticeDemo.tsx 의 '시각화' 칸 안에서만 써요
 * - nums 의 값이 높이가 다른 입체 기둥으로 서 있어요. (값이 클수록 높아요)
 * - 보라 캐릭터가 반복문 회차(i)마다 해당 기둥 위로 폴짝 뛰어 올라가요.
 * - 지금까지의 최댓값(max) 기둥 위에는 왕관이 떠 있고, max 가 바뀌면 왕관이 새 기둥으로 옮겨 가요.
 * - 3D 모델 없이 SVG 면(앞 · 위 · 옆)과 그라데이션으로 입체감을 내요. 스타일: lerny-practice-viz3d.css
 */

import './lerny-practice-viz3d.css'

interface Props {
  nums: number[]
  /** 지금 회차가 가리키는 칸(i). 실행 전이면 0 */
  at: number
  /** 지금까지의 최댓값이 있는 칸 */
  maxAt: number
  /** 회차 번호 — 바뀔 때마다 캐릭터가 한 번 뛰어요 */
  hop: number
}

const BASE_Y = 168
const W = 54 // 기둥 앞면 너비
const D = 16 // 깊이(오른쪽 위로 비껴 보이는 정도)
const GAP = 34
const X0 = 46
const UNIT = 8.4 // 값 1 당 높이

const colX = (i: number) => X0 + i * (W + GAP)
const colH = (v: number) => 18 + v * UNIT

export default function PracticeViz3D({ nums, at, maxAt, hop }: Props) {
  const top = (i: number) => BASE_Y - colH(nums[i])
  // 캐릭터 · 왕관이 설 자리 (기둥 윗면 가운데)
  const cx = (i: number) => colX(i) + W / 2 + D / 2
  const cy = (i: number) => top(i) - D / 2

  return (
    <svg className="pd3" viewBox="0 -24 400 234" role="img" aria-label="nums 값이 기둥으로 서 있고, 캐릭터가 i 번째 기둥 위로 뛰어 올라가요">
      <defs>
        <linearGradient id="pd3-front" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#efe7ff" />
          <stop offset="100%" stopColor="#ddd0fb" />
        </linearGradient>
        <linearGradient id="pd3-front-on" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#b48cff" />
          <stop offset="100%" stopColor="#7b45f0" />
        </linearGradient>
        <radialGradient id="pd3-body" cx="0.35" cy="0.3" r="0.8">
          <stop offset="0%" stopColor="#d9c7ff" />
          <stop offset="45%" stopColor="#8d5cf6" />
          <stop offset="100%" stopColor="#4b1fb8" />
        </radialGradient>
        <radialGradient id="pd3-floor" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="rgba(123,69,240,0.18)" />
          <stop offset="100%" stopColor="rgba(123,69,240,0)" />
        </radialGradient>
      </defs>

      {/* 바닥 판 */}
      <ellipse cx="200" cy={BASE_Y + 8} rx="190" ry="20" fill="url(#pd3-floor)" />
      <path d={`M ${X0 - 18} ${BASE_Y} L ${X0 - 18 + D} ${BASE_Y - D} L ${colX(nums.length - 1) + W + D + 18} ${BASE_Y - D} L ${colX(nums.length - 1) + W + 18} ${BASE_Y} Z`} className="pd3-plate" />

      {/* 기둥 */}
      {nums.map((v, i) => {
        const x = colX(i)
        const t = top(i)
        const on = i === at
        return (
          <g key={i} className={`pd3-col ${on ? 'on' : ''} ${i === maxAt ? 'max' : ''}`}>
            {/* 옆면 */}
            <path d={`M ${x + W} ${t} L ${x + W + D} ${t - D} L ${x + W + D} ${BASE_Y - D} L ${x + W} ${BASE_Y} Z`} className="side" />
            {/* 앞면 */}
            <rect x={x} y={t} width={W} height={BASE_Y - t} fill={on ? 'url(#pd3-front-on)' : 'url(#pd3-front)'} className="front" />
            {/* 윗면 */}
            <path d={`M ${x} ${t} L ${x + D} ${t - D} L ${x + W + D} ${t - D} L ${x + W} ${t} Z`} className="top" />
            <text x={x + W / 2} y={t + 22} className="val">{v}</text>
            <text x={x + W / 2} y={BASE_Y + 20} className="idx">{i}</text>
          </g>
        )
      })}

      {/* 왕관 — 지금까지의 최댓값 기둥 위 */}
      <g className="pd3-crown" style={{ transform: `translate(${cx(maxAt) + 14}px, ${cy(maxAt) - 34}px)` }}>
        <g className="bob">
          <path d="M -10 4 L -12 -8 L -5 -2 L 0 -11 L 5 -2 L 12 -8 L 10 4 Z" />
          <rect x="-10" y="4" width="20" height="4" rx="1.5" />
          <text x="0" y="-15" className="lbl">max</text>
        </g>
      </g>

      {/* 캐릭터 — 회차마다 i 번째 기둥 위로 폴짝 */}
      <g className="pd3-char" style={{ transform: `translate(${cx(at) - 6}px, ${cy(at)}px)` }}>
        <ellipse cx="0" cy="1" rx="13" ry="3.6" className="shadow" />
        <g className="hop" key={hop}>
          <g className="squish">
            {/* 새싹 */}
            <path d="M 0 -30 q -1 -6 0 -9" className="stem" />
            <path d="M 0 -38 q 6 -6 11 -2 q -5 5 -11 2 Z" className="leaf" />
            {/* 몸 */}
            <ellipse cx="0" cy="-15" rx="14" ry="15.5" fill="url(#pd3-body)" />
            <ellipse cx="-5" cy="-23" rx="5" ry="3.2" fill="#ffffff" opacity="0.55" />
            {/* 눈 · 볼 · 입 */}
            <g className="eyes">
              <ellipse cx="-4.6" cy="-16" rx="2.6" ry="3.2" fill="#ffffff" />
              <ellipse cx="4.6" cy="-16" rx="2.6" ry="3.2" fill="#ffffff" />
              <circle cx="-4.2" cy="-15.2" r="1.6" fill="#1e0b3d" />
              <circle cx="5" cy="-15.2" r="1.6" fill="#1e0b3d" />
            </g>
            <ellipse cx="-8.5" cy="-11.5" rx="2.2" ry="1.2" fill="#ffb3c4" opacity="0.8" />
            <ellipse cx="8.5" cy="-11.5" rx="2.2" ry="1.2" fill="#ffb3c4" opacity="0.8" />
            <path d="M -2 -10.5 q 2 2 4 0" className="mouth" />
            {/* 발 */}
            <ellipse cx="-5" cy="0" rx="4" ry="2.4" fill="#5a2bc9" />
            <ellipse cx="5" cy="0" rx="4" ry="2.4" fill="#5a2bc9" />
          </g>
        </g>
      </g>
    </svg>
  )
}
