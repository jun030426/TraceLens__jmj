/**
 * [공용 컴포넌트] 가로로 늘어선 필터 칩 버튼 (맨 앞 '전체' + 항목들)
 * - 학생 퀴즈 목록의 강의 필터, 교수자 강의 필터(CourseFilter)에서 사용
 * - 스타일: styles/quiz.css 의 .quiz-filter
 */

interface FilterChipsProps<T extends string | number> {
  options: { value: T; label: string }[]
  /** null = 전체 */
  value: T | null
  onChange: (value: T | null) => void
  /** '전체' 버튼 글자 (null 이면 '전체' 버튼을 숨김) */
  allLabel?: string | null
  ariaLabel?: string
}

export default function FilterChips<T extends string | number>({
  options,
  value,
  onChange,
  allLabel = '전체',
  ariaLabel = '필터',
}: FilterChipsProps<T>) {
  const chip = (v: T | null, label: string) => (
    <button
      key={v ?? 'all'}
      type="button"
      role="tab"
      aria-selected={value === v}
      className={value === v ? 'active' : undefined}
      onClick={() => onChange(v)}
    >
      {label}
    </button>
  )

  return (
    <div className="quiz-filter" role="tablist" aria-label={ariaLabel}>
      {allLabel !== null && chip(null, allLabel)}
      {options.map((o) => chip(o.value, o.label))}
    </div>
  )
}
