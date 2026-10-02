/**
 * [공용 컴포넌트] 붙어 있는 선택 버튼 묶음 (예: 전체 | 공지 | 자료)
 * - 교수자 수강생 관리(상태 필터), 공지·자료 페이지(종류 선택/필터)에서 사용
 * - 스타일: styles/professor.css 의 .prof-segment
 */

import type { ReactNode } from 'react'

interface SegmentButtonsProps<T extends string> {
  options: readonly T[]
  value: T
  onChange: (value: T) => void
  /** 버튼 안에 보여줄 내용 (기본: 값 그대로) */
  renderLabel?: (value: T) => ReactNode
  ariaLabel: string
  className?: string
}

export default function SegmentButtons<T extends string>({
  options,
  value,
  onChange,
  renderLabel = (v) => v,
  ariaLabel,
  className = '',
}: SegmentButtonsProps<T>) {
  return (
    <div className={`prof-segment ${className}`.trim()} role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o}
          type="button"
          className={value === o ? 'active' : undefined}
          onClick={() => onChange(o)}
        >
          {renderLabel(o)}
        </button>
      ))}
    </div>
  )
}
