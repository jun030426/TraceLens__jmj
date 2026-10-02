/**
 * [학생 공용 컴포넌트] 강의 목록 한 줄의 왼쪽 '강의' 칸 — 색 아이콘 + 강의명 + 작은 설명
 * - 학생 수강목록(CourseList)과 출석 현황(Attendance) 표에서 사용
 * - 스타일: styles/student-courses.css 의 .s-title
 */

import type { ReactNode } from 'react'
import type { ProfessorCourse } from '../../types/course'

interface CourseTitleCellProps {
  course: ProfessorCourse
  /** 강의명 아래 작은 글씨 */
  meta: ReactNode
  /** 그 아래 강의 소개 등 */
  children?: ReactNode
}

export default function CourseTitleCell({ course, meta, children }: CourseTitleCellProps) {
  return (
    <div className="s-title">
      <span className="s-icon">{course.title.charAt(0)}</span>
      <div>
        <strong>{course.title}</strong>
        <small>{meta}</small>
        {children}
      </div>
    </div>
  )
}
