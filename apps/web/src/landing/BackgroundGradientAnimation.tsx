/**
 * [랜딩 맨 아래] 움직이는 그라데이션 배경 — Aceternity UI 의 Background Gradient Animation 을 이 프로젝트에 맞게 옮겼어요.
 * - 흐린 색 덩어리 다섯 개가 각자 위아래 · 좌우 · 원을 그리며 천천히 움직이고, 마우스를 따라오는 덩어리가 하나 더 있어요.
 * - 원본과 다른 점 (이 프로젝트에 Tailwind · shadcn 이 없어서):
 *   · Tailwind 클래스 · animate-first~fifth 대신 같은 값의 CSS 를 landing/lerny-gradient-anim.css 에 썼어요 (.bga-*).
 *   · cn(clsx + tailwind-merge) 대신 클래스 이름을 공백으로 이어 붙여요.
 *   · 색 변수를 document.body 가 아니라 이 영역에만 걸어요 (다른 화면 색과 섞이지 않게).
 *   · 내용이 색 덩어리 위에 있어서, 마우스 움직임은 바깥 영역 전체에서 받아요.
 *     따라오는 움직임도 마우스가 움직일 때 한 번씩이 아니라 매 프레임 부드럽게 따라가요.
 *   · 크기는 화면 전체(h-screen w-screen)가 아니라 감싼 영역 크기를 따라가요.
 */

import { useEffect, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from 'react'
import './lerny-gradient-anim.css'

const cn = (...c: (string | undefined | false)[]) => c.filter(Boolean).join(' ')

export const BackgroundGradientAnimation = ({
  gradientBackgroundStart = 'rgb(108, 0, 162)',
  gradientBackgroundEnd = 'rgb(0, 17, 82)',
  firstColor = '18, 113, 255',
  secondColor = '221, 74, 255',
  thirdColor = '100, 220, 255',
  fourthColor = '200, 50, 50',
  fifthColor = '180, 180, 50',
  pointerColor = '140, 100, 255',
  size = '80%',
  blendingValue = 'hard-light',
  children,
  className,
  interactive = true,
  containerClassName,
}: {
  gradientBackgroundStart?: string
  gradientBackgroundEnd?: string
  firstColor?: string
  secondColor?: string
  thirdColor?: string
  fourthColor?: string
  fifthColor?: string
  pointerColor?: string
  size?: string
  blendingValue?: string
  children?: ReactNode
  className?: string
  interactive?: boolean
  containerClassName?: string
}) => {
  const interactiveRef = useRef<HTMLDivElement>(null)
  const target = useRef({ x: 0, y: 0 })
  const [isSafari, setIsSafari] = useState(false)

  useEffect(() => {
    setIsSafari(/^((?!chrome|android).)*safari/i.test(navigator.userAgent))
  }, [])

  // 마우스를 따라오는 덩어리: 목표 지점까지 매 프레임 1/20 씩 다가가요 (원본과 같은 비율)
  useEffect(() => {
    if (!interactive) return
    let raf = 0
    const cur = { x: 0, y: 0 }
    const move = () => {
      const el = interactiveRef.current
      if (el) {
        cur.x += (target.current.x - cur.x) / 20
        cur.y += (target.current.y - cur.y) / 20
        el.style.transform = `translate(${Math.round(cur.x)}px, ${Math.round(cur.y)}px)`
      }
      raf = requestAnimationFrame(move)
    }
    raf = requestAnimationFrame(move)
    return () => cancelAnimationFrame(raf)
  }, [interactive])

  const handleMouseMove = (event: MouseEvent<HTMLDivElement>) => {
    const el = interactiveRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const m = new DOMMatrixReadOnly(getComputedStyle(el).transform)
    // 지금 옮겨진 만큼을 빼서, 덩어리의 원래 자리 기준 좌표로 (원본은 옮겨진 자리 기준이라 계속 밀려나요)
    target.current = { x: event.clientX - (rect.left - m.m41), y: event.clientY - (rect.top - m.m42) }
  }

  const vars = {
    '--gradient-background-start': gradientBackgroundStart,
    '--gradient-background-end': gradientBackgroundEnd,
    '--first-color': firstColor,
    '--second-color': secondColor,
    '--third-color': thirdColor,
    '--fourth-color': fourthColor,
    '--fifth-color': fifthColor,
    '--pointer-color': pointerColor,
    '--size': size,
    '--blending-value': blendingValue,
  } as CSSProperties

  return (
    <div className={cn('bga-container', containerClassName)} style={vars} onMouseMove={interactive ? handleMouseMove : undefined}>
      <svg className="bga-hidden" aria-hidden="true">
        <defs>
          <filter id="blurMe">
            <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="blur" />
            <feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -8" result="goo" />
            <feBlend in="SourceGraphic" in2="goo" />
          </filter>
        </defs>
      </svg>
      <div className={cn('bga-content', className)}>{children}</div>
      <div className={cn('bga-gradients', isSafari ? 'is-safari' : undefined)} aria-hidden="true">
        <div className="bga-blob bga-first" />
        <div className="bga-blob bga-second" />
        <div className="bga-blob bga-third" />
        <div className="bga-blob bga-fourth" />
        <div className="bga-blob bga-fifth" />
        {interactive && <div ref={interactiveRef} className="bga-pointer" />}
      </div>
    </div>
  )
}
