/**
 * [학생 공용 헤더] 학생 페이지 상단 — 메뉴(강의 자료·챗봇·퀴즈) + 프로필(내 정보·출석 현황·로그아웃)
 */

import AppHeader, { type NavItem } from './AppHeader'
import { useAuth } from '../../hooks/useAuth'

export type StudentNavKey = 'materials' | 'chatbot' | 'quiz'

const NAV_ITEMS: NavItem<StudentNavKey>[] = [
  { key: 'materials', label: '강의 자료', href: '/courses' },
  { key: 'chatbot', label: '챗봇', href: '/ai' },
  { key: 'quiz', label: '퀴즈', href: '/quiz' },
]

const MENU_LINKS = [
  { label: '내 정보', href: '/mypage' },
  { label: '출석 현황', href: '/attendance' },
]

interface StudentHeaderProps {
  active?: StudentNavKey
  /** true 면 메뉴와 배경 바 없이 로고 + 프로필만 (로그인 직후 첫 화면용) */
  minimal?: boolean
}

export default function StudentHeader({ active, minimal = false }: StudentHeaderProps) {
  const { user, logout } = useAuth()

  return (
    <AppHeader
      navItems={NAV_ITEMS}
      active={active}
      minimal={minimal}
      userName={user?.name ?? '게스트'}
      userSub={user?.email ?? ''}
      menuLinks={MENU_LINKS}
      onLogout={logout}
    />
  )
}
