/**
 * [공용 레이아웃] 로그인 후 페이지 공통 틀 — 바깥 div + (학생/교수자) 헤더 + main
 * - 학생 페이지: role="student", 교수자 페이지: role="professor"
 * - 스타일: styles/page-common.css (.course-list-page, .course-list-main)
 */

import type { CSSProperties, ReactNode } from 'react'
import StudentHeader, { type StudentNavKey } from './StudentHeader'
import ProfessorHeader, { type ProfessorNavKey } from './ProfessorHeader'

type PageLayoutProps = {
  /** 바깥 div 에 더 붙일 클래스 (예: 강의 색상 course-card-purple) */
  className?: string
  style?: CSSProperties
  /** main 클래스 (기본: course-list-main) */
  mainClassName?: string
  children: ReactNode
} & ({ role: 'student'; active?: StudentNavKey } | { role: 'professor'; active?: ProfessorNavKey })

export default function PageLayout(props: PageLayoutProps) {
  const { className = '', style, mainClassName = 'course-list-main', children } = props
  const isProfessor = props.role === 'professor'

  // 중복 없이 클래스 합치기
  const classes = [
    'study-landing',
    'student-landing',
    'course-list-page',
    isProfessor ? 'professor-page' : '',
    ...className.split(' '),
  ].filter(Boolean)

  return (
    <div className={[...new Set(classes)].join(' ')} style={style}>
      {props.role === 'professor' ? (
        <ProfessorHeader active={props.active} />
      ) : (
        <StudentHeader active={props.active} />
      )}
      <main className={mainClassName}>{children}</main>
    </div>
  )
}
