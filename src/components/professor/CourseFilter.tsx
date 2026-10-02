/**
 * [교수자 공용 컴포넌트] 담당 강의 필터 칩 (전체 강의 / 강의1 / 강의2 …)
 * - 교수자 수강생 관리(ProfessorStudents), 공지·자료(ProfessorNotices)에서 사용
 */

import FilterChips from '../common/FilterChips'
import { useCourseStore } from '../../store/courseStore'

interface CourseFilterProps {
  value: number | null // null = 전체
  onChange: (courseId: number | null) => void
}

export default function CourseFilter({ value, onChange }: CourseFilterProps) {
  const { courses } = useCourseStore()

  return (
    <FilterChips
      ariaLabel="강의별 필터"
      allLabel="전체 강의"
      options={courses.map((c) => ({ value: c.id, label: c.title }))}
      value={value}
      onChange={onChange}
    />
  )
}
