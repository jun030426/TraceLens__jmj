/**
 * [교수자 수강생 관리 페이지] 주소: /professor/students
 * - 전체(또는 강의별) 수강생의 진도율·퀴즈·출석 요약 + 수강생 표 + CSV 내보내기
 */

import { useState } from 'react'
import PageLayout from '../../components/layout/PageLayout'
import PageHeading from '../../components/common/PageHeading'
import SummaryCards from '../../components/common/SummaryCards'
import CourseFilter from '../../components/professor/CourseFilter'
import StudentManager, { downloadCsv } from '../../components/professor/StudentManager'
import { useCourseStore } from '../../store/courseStore'
import { studentStatus } from '../../utils/course'
import { average } from '../../utils/format'

export default function ProfessorStudents() {
  const { students } = useCourseStore()
  const [courseId, setCourseId] = useState<number | null>(null)
  const inCourse = courseId === null ? students : students.filter((s) => s.courseId === courseId)
  const needCare = inCourse.filter((s) => studentStatus(s) !== '우수').length

  return (
    <PageLayout role="professor">
      <PageHeading
        label="STUDENTS"
        title="수강생 관리"
        description="수강생별 진도율·퀴즈·출석을 확인하고 도움이 필요한 학생을 찾아보세요."
      >
        <button type="button" className="quiz-generate-btn" onClick={() => downloadCsv(inCourse)}>
          <span>↓</span>
          CSV 내보내기
        </button>
      </PageHeading>

      <CourseFilter value={courseId} onChange={setCourseId} />

      <SummaryCards
        ariaLabel="수강생 요약"
        items={[
          { label: '수강생', value: inCourse.length, unit: '명' },
          { label: '평균 진도율', value: average(inCourse.map((s) => s.progress)), unit: '%' },
          { label: '평균 출석률', value: average(inCourse.map((s) => s.attendance)), unit: '%' },
          {
            label: '관심 필요',
            value: needCare,
            unit: '명',
            valueClassName: needCare > 0 ? 'prof-text-danger' : undefined,
          },
        ]}
      />

      <StudentManager courseId={courseId} />
    </PageLayout>
  )
}
