/**
 * [공용 컴포넌트] 러니 로고 — 누르면 홈으로 이동 (로그인 상태면 학생 홈, 아니면 첫 랜딩)
 */

import type { MouseEvent } from 'react'
import { useAuth } from '../../hooks/useAuth'

type LogoProps = {
  className?: string
  /** 따로 넘기면 기본 이동 대신 이 함수가 실행됨 */
  onClick?: () => void
}

export default function Logo({ className = '', onClick }: LogoProps) {
  const { isLoggedIn } = useAuth()

  // 로그인 했으면 학생용 랜딩, 안 했으면 첫 랜딩 페이지
  const homeHref = isLoggedIn ? '/student' : '/'

  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (onClick) {
      e.preventDefault()
      onClick()
    }
  }

  return (
    <a href={homeHref} onClick={handleClick} aria-label="홈으로 이동">
      <img src="/lerny-logo.png" alt="러니" className={`app-logo ${className}`} />
    </a>
  )
}
