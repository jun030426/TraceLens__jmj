/**
 * [교수자 공용 헤더] 교수자 페이지 상단 — 로고 + '교수자' 배지 + 메뉴(강의 자료) + 프로필(내 정보·로그아웃)
 */

import AppHeader, { type NavItem } from './AppHeader'
import { useProfessorAuth } from '../../hooks/useAuth'

export type ProfessorNavKey = 'materials'

const NAV_ITEMS: NavItem<ProfessorNavKey>[] = [
  { key: 'materials', label: '강의 자료', href: '/professor/notices' },
]

const MENU_LINKS = [{ label: '내 정보', href: '/professor/mypage' }]

interface ProfessorHeaderProps {
  active?: ProfessorNavKey
  /** true 면 메뉴와 배경 바 없이 로고 + 프로필만 */
  minimal?: boolean
}

export default function ProfessorHeader({ active, minimal = false }: ProfessorHeaderProps) {
  const { user, logout } = useProfessorAuth()

  return (
    <AppHeader
      navItems={NAV_ITEMS}
      active={active}
      minimal={minimal}
      logoClassName="professor-logo"
      logoExtra={<span className="professor-role-badge">교수자</span>}
      avatarClassName="professor-avatar"
      userName={user?.name ?? '게스트'}
      userSub={user ? user.department || user.email : ''}
      menuLinks={MENU_LINKS}
      onLogout={logout}
    />
  )
}
