/**
 * [공용 컴포넌트] 페이지 상단 요약 숫자 카드 줄 (예: 수강 과목 3과목 · 평균 진도율 68%)
 * - 학생/교수자 페이지 대부분에서 사용 (스타일: styles/page-common.css 의 .course-summary)
 */

import type { ReactNode } from 'react'

export interface SummaryItem {
  label: ReactNode
  value: ReactNode
  /** 숫자 뒤 작은 글씨 단위 (예: '%', '명') */
  unit?: ReactNode
  /** 숫자에 붙일 클래스 (예: 경고색 'prof-text-danger') */
  valueClassName?: string
}

interface SummaryCardsProps {
  items: SummaryItem[]
  ariaLabel: string
  className?: string
}

export default function SummaryCards({ items, ariaLabel, className = '' }: SummaryCardsProps) {
  return (
    <section className={`course-summary ${className}`.trim()} aria-label={ariaLabel}>
      {items.map((item, i) => (
        <div key={i} className="course-summary-item">
          <span>{item.label}</span>
          <strong className={item.valueClassName}>
            {item.value}
            {item.unit !== undefined && <small>{item.unit}</small>}
          </strong>
        </div>
      ))}
    </section>
  )
}
