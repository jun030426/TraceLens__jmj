/**
 * [교수자 첫 화면 · 담당 강의 목록 페이지] 주소: /professor
 * - 강의별 수강생 수 · 진행 주차 · 대기 중인 수강 신청 표시
 * - '강의 추가' 버튼 → CourseModal 로 새 강의 만들기
 * - 강의를 누르면 강의 상세(/professor/courses/:id)로 이동
 */

import { useState } from 'react'
import PageLayout from '../../components/layout/PageLayout'
import PageHeading, { SemesterBadge } from '../../components/common/PageHeading'
import EmptyState from '../../components/common/EmptyState'
import CourseModal from '../../components/professor/CourseModal'
import { useProfessorAuth } from '../../hooks/useAuth'
import { addCourse, pendingRequestsOf, studentsOf, useCourseStore } from '../../store/courseStore'
import { accentStyle, courseCode, weekRate } from '../../utils/course'

export default function ProfessorDashboard() {
  const { user } = useProfessorAuth()
  const db = useCourseStore()
  const { courses } = db
  const [courseModalOpen, setCourseModalOpen] = useState(false)
  const [justAddedId, setJustAddedId] = useState<number | null>(null)

  return (
    <PageLayout role="professor">
      <PageHeading
        label="MY COURSES"
        title="강의 목록"
        description={`${user?.name ?? '교수'}님이 담당하는 강의예요.`}
      >
        <div className="prof-heading-actions">
          <SemesterBadge />
          <button
            type="button"
            className="quiz-generate-btn"
            onClick={() => setCourseModalOpen(true)}
          >
            <span>+</span>
            강의 추가
          </button>
        </div>
      </PageHeading>

      {courses.length === 0 ? (
        <EmptyState
          title="아직 담당 강의가 없어요"
          description="오른쪽 위 ‘강의 추가’ 버튼으로 강의를 만들어 보세요."
        />
      ) : (
        <section className="prof-clist" aria-label="담당 강의 목록">
          <div className="prof-clist-head" aria-hidden="true">
            <span>강의</span>
            <span>수업 시간</span>
            <span>수강생</span>
            <span>진행</span>
            <span>신청</span>
            <span />
          </div>

          <ul>
            {courses.map((c) => {
              const count = studentsOf(db, c.id).length
              const waiting = pendingRequestsOf(db, c.id).length

              return (
                <li key={c.id}>
                  <a
                    href={`/professor/courses/${c.id}`}
                    className={`prof-clist-row course-card-${c.color} ${justAddedId === c.id ? 'prof-just-added' : ''}`}
                    style={accentStyle(c)}
                  >
                    <div className="prof-clist-title">
                      <span className="prof-clist-icon">{c.title.charAt(0)}</span>
                      <div>
                        <strong>{c.title}</strong>
                        <small>
                          {courseCode(c)} · {c.credits}학점
                        </small>
                      </div>
                    </div>

                    <span className="prof-clist-cell" data-label="수업 시간">
                      {c.schedule}
                    </span>

                    <span className="prof-clist-cell" data-label="수강생">
                      <b>{count}</b>/{c.capacity}명
                    </span>

                    <span className="prof-clist-cell" data-label="진행">
                      <span className="prof-clist-week">
                        <b>{c.week}</b>/{c.totalWeeks}주
                      </span>
                      <span className="prof-clist-bar">
                        <i style={{ width: `${weekRate(c)}%` }} />
                      </span>
                    </span>

                    <span className="prof-clist-cell" data-label="신청">
                      {waiting > 0 ? (
                        <em className="prof-clist-badge">{waiting}건 대기</em>
                      ) : (
                        <span className="prof-muted">-</span>
                      )}
                    </span>

                    <span className="prof-clist-go" aria-hidden="true">
                      ›
                    </span>
                  </a>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {courseModalOpen && (
        <CourseModal
          professorName={user?.name ?? '교수'}
          onClose={() => setCourseModalOpen(false)}
          onSubmit={(input) => {
            const course = addCourse(input)
            setCourseModalOpen(false)
            setJustAddedId(course.id)
          }}
        />
      )}
    </PageLayout>
  )
}
