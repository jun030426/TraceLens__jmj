import type { ReactNode } from 'react'
import { ROUTES } from '../router'
import { Link } from './Link'

const NAV = [
  { to: ROUTES.about, label: '소개' },
  { to: ROUTES.help, label: '도움말' },
  { to: ROUTES.settings, label: '설정' },
]

/* 마크는 이 도구가 하는 일 그대로다 — 실행의 한 시점을 가리키는 커서, 그리고
   그 시점에 살아 있는 두 칸. */
export function Mark() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
      <rect x="1.5" y="5.5" width="7" height="9" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <rect x="8.5" y="5.5" width="7" height="9" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M18 3.2 L 18 16.8" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

/** 한 제품에 내비게이션은 하나다. 워크벤치는 오른쪽 끝만 실행 상태로 바꿔 쓴다. */
export function Nav({ trailing }: { trailing?: ReactNode }) {
  return (
    <header className="tl-nav">
      <Link to={ROUTES.landing} className="tl-brand">
        <Mark />
        TraceLens
      </Link>
      <nav className="tl-navlinks" aria-label="주요">
        {NAV.map(n => (
          <Link key={n.to} to={n.to} className="tl-navlink">
            {n.label}
          </Link>
        ))}
      </nav>
      {trailing ?? (
        <Link to={ROUTES.app} className="tl-btn tl-btn--sm">
          실행하기
        </Link>
      )}
    </header>
  )
}

export function Footer() {
  return (
    <footer className="tl-footer">
      <div className="tl-footer__row">
        <div>
          <p className="tl-note" style={{ color: 'var(--ink-2)', fontWeight: 600 }}>
            TraceLens
          </p>
          <p className="tl-note" style={{ marginTop: 4, maxWidth: '54ch' }}>
            코드 실행은 브라우저 안에서 끝납니다. 연출을 만들 때만 코드와 요약본이 외부 모델로 전송되며,{' '}
            <Link to={ROUTES.settings} className="tl-link">
              설정
            </Link>
            에서 끌 수 있습니다.
          </p>
        </div>
        <p className="tl-note" style={{ maxWidth: '36ch' }}>
          The trace decides what happened;
          <br />
          the Director decides what is worth showing.
        </p>
      </div>
    </footer>
  )
}

export function Page({ children, still }: { children: ReactNode; still: boolean }) {
  return (
    <div className="tl" data-still={still ? 'true' : 'false'}>
      <a className="tl-skip" href="#tl-main">
        본문으로 건너뛰기
      </a>
      <Nav />
      <div id="tl-main" tabIndex={-1}>
        {children}
      </div>
      <Footer />
    </div>
  )
}
