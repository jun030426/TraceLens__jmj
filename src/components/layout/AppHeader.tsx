/**
 * [공용 레이아웃] 상단 헤더 틀 — 로고 + 메뉴 + 프로필 드롭다운(내 정보·로그아웃)
 * - 직접 쓰지 않고 StudentHeader / ProfessorHeader 가 내용을 채워서 사용해요.
 * - 스타일: styles/landing.css(헤더) + styles/header-profile.css(프로필 메뉴)
 */

import { useCallback, useRef, useState, type ReactNode } from 'react'
import Logo from '../common/Logo'
import { useDismiss } from '../../hooks/useDismiss'

export interface NavItem<K extends string> {
  key: K
  label: string
  href: string
}

interface AppHeaderProps<K extends string> {
  navItems: NavItem<K>[]
  /** 지금 페이지에 해당하는 메뉴 (강조 표시) */
  active?: K
  /** true 면 메뉴와 배경 바 없이 로고 + 프로필만 보여줘요 (로그인 직후 첫 화면용) */
  minimal?: boolean
  /** 로고 옆에 붙는 것 (예: 교수자 배지) */
  logoExtra?: ReactNode
  logoClassName?: string
  /** 프로필 동그라미에 붙일 추가 클래스 (교수자는 색이 달라요) */
  avatarClassName?: string
  userName: string
  /** 프로필 메뉴 이름 아래 작은 글씨 (이메일 / 학과) */
  userSub: string
  /** 프로필 메뉴 링크 (로그아웃 위) */
  menuLinks: { label: string; href: string }[]
  onLogout: () => void
}

export default function AppHeader<K extends string>({
  navItems,
  active,
  minimal = false,
  logoExtra,
  logoClassName = '',
  avatarClassName = '',
  userName,
  userSub,
  menuLinks,
  onLogout,
}: AppHeaderProps<K>) {
  const [profileOpen, setProfileOpen] = useState(false)
  const profileRef = useRef<HTMLDivElement>(null)
  const closeProfile = useCallback(() => setProfileOpen(false), [])

  // 프로필 메뉴 바깥 클릭 / ESC 로 닫기
  useDismiss(profileOpen, closeProfile, profileRef)

  const avatarClass = `student-profile-avatar ${avatarClassName}`.trim()

  return (
    <header className={`study-landing-header ${minimal ? 'study-landing-header-bare' : ''}`}>
      <div className="study-landing-header-inner">
        <div className={`study-landing-logo ${logoClassName}`.trim()}>
          <Logo />
          {logoExtra}
        </div>

        <div className="study-landing-header-right">
          {!minimal && (
            <nav className="study-landing-nav">
              {navItems.map((item) => (
                <a
                  key={item.key}
                  href={item.href}
                  className={active === item.key ? 'active' : undefined}
                  aria-current={active === item.key ? 'page' : undefined}
                >
                  {item.label}
                </a>
              ))}
            </nav>
          )}

          <div className="student-profile" ref={profileRef}>
            <button
              type="button"
              className="student-profile-trigger"
              onClick={() => setProfileOpen((prev) => !prev)}
              aria-haspopup="menu"
              aria-expanded={profileOpen}
            >
              <span className={avatarClass}>{userName.charAt(0)}</span>
              <span className="student-profile-name">{userName}</span>
              <span className={`student-profile-caret ${profileOpen ? 'open' : ''}`}>▾</span>
            </button>

            {profileOpen && (
              <div className="student-profile-menu" role="menu">
                <div className="student-profile-menu-header">
                  <span className={`${avatarClass} large`}>{userName.charAt(0)}</span>
                  <div>
                    <strong>{userName}</strong>
                    <span>{userSub}</span>
                  </div>
                </div>

                {menuLinks.map((link) => (
                  <a key={link.href} href={link.href} role="menuitem">
                    {link.label}
                  </a>
                ))}

                <div className="student-profile-divider" />

                <button
                  type="button"
                  role="menuitem"
                  className="student-profile-logout"
                  onClick={onLogout}
                >
                  로그아웃
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
