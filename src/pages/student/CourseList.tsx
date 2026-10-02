/**
 * [학생 수강목록 페이지] 주소: /courses  (헤더 메뉴 '강의 자료')
 * - '내 강의' 탭: 승인된 수강 강의 / '수강 신청' 탭: 신청 · 신청 취소
 *
 * 흐름: 교수자가 강의 추가 → 여기 '수강 신청' 탭에 보임 → 학생이 신청
 *       → 교수자 강의 상세의 '수강 신청 승인'에서 승인 → 여기 '내 강의' 탭에 들어옴
 *
 * 데이터는 전부 store/courseStore.ts 에서 가져와요 (지금은 브라우저에 저장하는 mock).
 * 백엔드 연결 시에는 courseStore 안쪽만 api/courseApi.ts 호출로 바꾸면 이 화면은 그대로 동작해요.
 */

import { useState } from 'react'
import PageLayout from '../../components/layout/PageLayout'
import PageHeading, { SemesterBadge } from '../../components/common/PageHeading'
import SummaryCards from '../../components/common/SummaryCards'
import EmptyState from '../../components/common/EmptyState'
import CourseTitleCell from '../../components/student/CourseTitleCell'
import EnrollDialog, { type EnrollDialogState } from '../../components/student/EnrollDialog'
import { useAuth, useStudentNo } from '../../hooks/useAuth'
import {
  cancelRequest,
  enrollmentStateOf,
  myCoursesOf,
  requestEnrollment,
  studentsOf,
  useCourseStore,
} from '../../store/courseStore'
import { accentStyle, courseCode } from '../../utils/course'
import { average } from '../../utils/format'
import type { EnrollmentState, ProfessorCourse } from '../../types/course'

type Tab = 'mine' | 'enroll'

const STATE_CLASS: Record<EnrollmentState, string> = {
  '신청 가능': 'open',
  '승인 대기': 'pending',
  '수강 중': 'enrolled',
  거절됨: 'rejected',
  '정원 마감': 'full',
}

export default function CourseList() {
  const { user } = useAuth()
  const studentNo = useStudentNo()
  const db = useCourseStore()
  const [notice, setNotice] = useState<string | null>(null)
  const [dialog, setDialog] = useState<EnrollDialogState | null>(null)

  // 내가 수강 중인 강의 (승인된 것)
  const myCourses = myCoursesOf(db, studentNo)

  // 신청 탭: 아직 수강 중이 아닌 강의
  const enrollable = db.courses
    .map((c) => ({ course: c, state: enrollmentStateOf(db, c.id, studentNo) }))
    .filter((x) => x.state !== '수강 중')
  const pendingCount = enrollable.filter((x) => x.state === '승인 대기').length

  const [tab, setTab] = useState<Tab>(myCourses.length > 0 ? 'mine' : 'enroll')

  const totalCredits = myCourses.reduce((sum, x) => sum + x.course.credits, 0)
  const avgProgress = average(myCourses.map((x) => x.enrollment.progress))

  // '신청하기' 버튼 → 확인 창 열기
  const openRequestDialog = (course: ProfessorCourse) => {
    setNotice(null)
    setDialog({ course, step: 'confirm' })
  }

  // 확인 창의 '신청' 버튼 → 실제 신청
  const confirmRequest = () => {
    if (!user || !dialog) return
    const result = requestEnrollment({
      courseId: dialog.course.id,
      studentName: user.name,
      studentNo,
      major: user.major ?? '',
      email: user.email,
    })
    setDialog(
      result.ok
        ? { ...dialog, step: 'done' }
        : { ...dialog, step: 'error', message: result.reason },
    )
  }

  const handleCancel = (courseId: number, title: string) => {
    cancelRequest(courseId, studentNo)
    setNotice(`‘${title}’ 수강 신청을 취소했어요.`)
  }

  // 탭 버튼
  const tabButton = (key: Tab, label: string, count: number) => (
    <button
      type="button"
      role="tab"
      aria-selected={tab === key}
      className={tab === key ? 'active' : undefined}
      onClick={() => setTab(key)}
    >
      {label} <em>{count}</em>
    </button>
  )

  return (
    <PageLayout role="student" active="materials">
      <PageHeading
        label="COURSES"
        title="수강목록"
        description="수강 중인 강의를 확인하고, 새 강의를 신청할 수 있어요."
      >
        <SemesterBadge />
      </PageHeading>

      <SummaryCards
        ariaLabel="수강 요약"
        items={[
          { label: '수강 과목', value: myCourses.length, unit: '과목' },
          { label: '총 학점', value: totalCredits, unit: '학점' },
          { label: '평균 진도율', value: avgProgress, unit: '%' },
          { label: '승인 대기', value: pendingCount, unit: '건' },
        ]}
      />

      <div className="s-tabs" role="tablist" aria-label="수강목록 보기">
        {tabButton('mine', '내 강의', myCourses.length)}
        {tabButton('enroll', '수강 신청', enrollable.length)}
      </div>

      {notice && (
        <div className="s-notice" role="status">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="알림 닫기">
            ✕
          </button>
        </div>
      )}

      {/* 내 강의 */}
      {tab === 'mine' &&
        (myCourses.length === 0 ? (
          <EmptyState
            title="아직 수강 중인 강의가 없어요"
            description="‘수강 신청’ 탭에서 강의를 신청하고 교수님 승인을 기다려 주세요."
          />
        ) : (
          <section className="s-list" aria-label="내 강의">
            <div className="s-list-head s-grid-mine" aria-hidden="true">
              <span>강의</span>
              <span>수업 시간</span>
              <span>진도율</span>
              <span>최근 학습</span>
            </div>
            <ul>
              {myCourses.map(({ course: c, enrollment: e }) => (
                <li
                  key={c.id}
                  className={`s-row s-grid-mine course-card-${c.color}`}
                  style={accentStyle(c)}
                >
                  <CourseTitleCell
                    course={c}
                    meta={`${courseCode(c)} · ${c.professor} · ${c.credits}학점`}
                  />
                  <span className="s-cell" data-label="수업 시간">
                    {c.schedule}
                  </span>
                  <span className="s-cell" data-label="진도율">
                    <span className="s-progress">
                      <span className="s-bar">
                        <i style={{ width: `${e.progress}%` }} />
                      </span>
                      <b>{e.progress}%</b>
                    </span>
                  </span>
                  <span className="s-cell s-muted" data-label="최근 학습">
                    {e.lastActive}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}

      {/* 수강 신청 */}
      {tab === 'enroll' &&
        (enrollable.length === 0 ? (
          <EmptyState
            title="신청할 수 있는 강의가 없어요"
            description="교수님이 강의를 개설하면 이곳에 표시됩니다."
          />
        ) : (
          <section className="s-list" aria-label="수강 신청 가능한 강의">
            <div className="s-list-head s-grid-enroll" aria-hidden="true">
              <span>강의</span>
              <span>수업 시간</span>
              <span>신청 현황</span>
              <span>상태</span>
              <span />
            </div>
            <ul>
              {enrollable.map(({ course: c, state }) => (
                <li
                  key={c.id}
                  className={`s-row s-grid-enroll course-card-${c.color}`}
                  style={accentStyle(c)}
                >
                  <CourseTitleCell
                    course={c}
                    meta={`${courseCode(c)} · ${c.professor} · ${c.credits}학점`}
                  >
                    {c.description && <p className="s-desc">{c.description}</p>}
                  </CourseTitleCell>
                  <span className="s-cell" data-label="수업 시간">
                    {c.schedule}
                  </span>
                  <span className="s-cell" data-label="신청 현황">
                    <b>{studentsOf(db, c.id).length}</b>/{c.capacity}명
                  </span>
                  <span className="s-cell" data-label="상태">
                    <span className={`enroll-state ${STATE_CLASS[state]}`}>{state}</span>
                  </span>
                  <span className="s-action">
                    {(state === '신청 가능' || state === '거절됨') && (
                      <button
                        type="button"
                        className="s-btn primary"
                        onClick={() => openRequestDialog(c)}
                      >
                        {state === '거절됨' ? '다시 신청' : '신청하기'}
                      </button>
                    )}
                    {state === '승인 대기' && (
                      <button
                        type="button"
                        className="s-btn ghost"
                        onClick={() => handleCancel(c.id, c.title)}
                      >
                        신청 취소
                      </button>
                    )}
                    {state === '정원 마감' && (
                      <button type="button" className="s-btn" disabled>
                        마감
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}

      {/* 수강 신청 확인 창 */}
      {dialog && (
        <EnrollDialog dialog={dialog} onConfirm={confirmRequest} onClose={() => setDialog(null)} />
      )}
    </PageLayout>
  )
}
