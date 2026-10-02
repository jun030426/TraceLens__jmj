/**
 * [공용 컴포넌트] 목록이 비었을 때 보여주는 안내 박스 (아이콘 + 제목 + 설명)
 * - 스타일: styles/page-common.css 의 .course-empty
 */

import type { ReactNode } from 'react'

interface EmptyStateProps {
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  className?: string
}

export default function EmptyState({
  icon = '▤',
  title,
  description,
  className = '',
}: EmptyStateProps) {
  return (
    <div className={`course-empty ${className}`.trim()}>
      <div className="course-empty-icon">{icon}</div>
      <h2>{title}</h2>
      {description && <p>{description}</p>}
    </div>
  )
}
