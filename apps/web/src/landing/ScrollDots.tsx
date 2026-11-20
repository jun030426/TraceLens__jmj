import { useEffect, useState } from 'react'
import './lerny-scroll-dots.css'

/* 왼쪽 스크롤 위치 점. 평소엔 흐릿하게, 마우스를 대면 또렷해지고 구간 이름이 보여요. 점을 누르면 그 구간으로 이동해요. */
const STOPS = [
  { sel: '.hp-root', label: '첫 화면' },
  { sel: '.cn-connect', label: '학생과 교수자 연결' },
  { sel: '.lw-flow', label: '하루의 학습' },
  { sel: '.lw-tools', label: '학습 도구' },
  { sel: '.lw-bridge', label: '교수자' },
  { sel: '.lm-hero', label: 'Lerny' },
  { sel: '.ln-closing', label: '시작하기' },
] as const

export default function ScrollDots() {
  const [active, setActive] = useState(0)

  useEffect(() => {
    let raf = 0
    const update = () => {
      raf = 0
      const line = window.innerHeight * 0.45
      let idx = 0
      STOPS.slice(0, -1).forEach((s, i) => {
        const el = document.querySelector(s.sel)
        if (el && el.getBoundingClientRect().top <= line) idx = i
      })
      // 맨 아래까지 내려오면 마지막 점
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) idx = STOPS.length - 1
      setActive(idx)
    }
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(update) }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

  const go = (i: number) => {
    const el = document.querySelector(STOPS[i].sel)
    if (!el) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    // The closing scene is transformed during the laptop animation. Its resting position is the end of the page.
    const top = i === STOPS.length - 1 ? document.documentElement.scrollHeight : el.getBoundingClientRect().top + window.scrollY
    window.scrollTo({ top, behavior: reduce ? 'instant' : 'smooth' })
  }

  return (
    <nav className="ls-dots" aria-label="페이지 구간">
      {STOPS.map((s, i) => (
        <button
          key={s.sel}
          type="button"
          className={i === active ? 'on' : undefined}
          aria-current={i === active ? 'true' : undefined}
          aria-label={s.label}
          onClick={() => go(i)}
        >
          <i />
          <span>{s.label}</span>
        </button>
      ))}
    </nav>
  )
}
