/**
 * [공용 컴포넌트] 페이지 상단 제목 영역 — 작은 영문 라벨 + 제목 + 설명 + (오른쪽) 버튼/학기 표시
 * - 학생/교수자 페이지 대부분에서 사용 (스타일: styles/page-common.css 의 .course-list-heading)
 */

import type { ReactNode } from 'react'

interface PageHeadingProps {
  /** 제목 위 작은 영문 라벨 (예: COURSES) */
  label: ReactNode
  title: ReactNode
  description?: ReactNode
  /** 오른쪽에 둘 버튼 · 학기 표시 등 */
  children?: ReactNode
}

export default function PageHeading({ label, title, description, children }: PageHeadingProps) {
  return (
    <section className="course-list-heading">
      <div>
        <span className="course-list-label">{label}</span>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children}
    </section>
  )
}

/** 학기 표시 배지 (예: 2026학년도 2학기) */
export function SemesterBadge() {
  return <span className="course-list-semester">2026학년도 2학기</span>
}
