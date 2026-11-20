/**
 * [랜딩 그림 도우미] 정해진 너비로 그린 데모 화면을 남은 자리(가로 · 세로)에 맞춰 통째로 줄여서 보여줘요
 * - 실습 · 챗봇 · 분석 데모는 학생용 화면처럼 내용이 많아서, 화면이 작으면 잘리지 않게 비율 그대로 축소해요.
 * - 스타일: styles/landing.css 의 .v-fit
 */

import { useLayoutEffect, useRef, type ReactNode } from 'react'

export default function DemoFit({ width, children }: { width: number; children: ReactNode }) {
  const outerRef = useRef<HTMLDivElement>(null)
  const innerRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const outer = outerRef.current
    const inner = innerRef.current
    if (!outer || !inner) return
    const fit = () => {
      const scale = Math.min(1, outer.clientWidth / width, outer.clientHeight / inner.offsetHeight)
      inner.style.transform = `translate(-50%, -50%) scale(${Math.max(0.1, scale)})`
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(outer)
    ro.observe(inner)
    return () => ro.disconnect()
  }, [width])

  return (
    <div ref={outerRef} className="v-fit">
      <div ref={innerRef} className="v-fit-inner" style={{ width }}>
        {children}
      </div>
    </div>
  )
}
