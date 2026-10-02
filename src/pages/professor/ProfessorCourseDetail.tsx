/**
 * [교수자 강의 상세 페이지] 주소: /professor/courses/:id  (강의 목록에서 강의를 누르면 열림)
 * - 강의 요약 · 진행 현황 · 진도율 분포 · 수강 신청 승인/거절 · 최근 공지 · 수강생 관리 표
 */

import PageLayout from '../../components/layout/PageLayout'
import PageHeading from '../../components/common/PageHeading'
import SummaryCards from '../../components/common/SummaryCards'
import StudentManager from '../../components/professor/StudentManager'
import CourseNotFound from '../../components/professor/CourseNotFound'
import { KindBadge } from '../../components/professor/NoticeParts'
import {
  approveRequest,
  pendingRequestsOf,
  rejectRequest,
  removeStudent,
  studentsOf,
  useCourseStore,
} from '../../store/courseStore'
import { fetchNotices } from '../../api/noticeApi'
import { useApiData } from '../../hooks/useApiData'
import { accentStyle, courseCode, weekRate as getWeekRate } from '../../utils/course'
import { average } from '../../utils/format'

// 진도율 분포 구간
const BUCKETS = [
  { label: '0–29%', min: 0, max: 29 },
  { label: '30–49%', min: 30, max: 49 },
  { label: '50–79%', min: 50, max: 79 },
  { label: '80–100%', min: 80, max: 100 },
]

// 막대 툴팁에 보여줄 최대 인원 (넘으면 '외 N명')
const MAX_TIP = 8

interface ProfessorCourseDetailProps {
  courseId: number
}

export default function ProfessorCourseDetail({ courseId }: ProfessorCourseDetailProps) {
  const db = useCourseStore()
  const course = db.courses.find((c) => c.id === courseId)
  // 이 강의의 최근 공지·자료 (api/noticeApi.ts)
  const { data: noticeData } = useApiData(() => fetchNotices(courseId), [courseId])

  if (!course) return <CourseNotFound />

  const students = studentsOf(db, course.id)
  const pendingRequests = pendingRequestsOf(db, course.id)
  const notices = noticeData ?? []

  const avgProgress = average(students.map((s) => s.progress))
  const quizTakers = students.filter((s) => s.quizAvg > 0)
  const avgQuiz = average(quizTakers.map((s) => s.quizAvg))
  const avgAttendance = average(students.map((s) => s.attendance))
  const weekRate = getWeekRate(course)

  // 구간별 학생 (진도율 낮은 순) — 막대에 마우스를 올리면 이름이 보여요
  const bucketStudents = BUCKETS.map((b) =>
    students
      .filter((s) => s.progress >= b.min && s.progress <= b.max)
      .sort((x, y) => x.progress - y.progress),
  )
  const bucketCounts = bucketStudents.map((list) => list.length)
  const maxBucket = Math.max(1, ...bucketCounts)

  const approveAll = () => {
    if (!confirm(`대기 중인 신청 ${pendingRequests.length}건을 모두 승인할까요?`)) return
    pendingRequests.forEach((r) => approveRequest(r.id))
  }

  return (
    <PageLayout
      role="professor"
      className={`course-card-${course.color}`}
      style={accentStyle(course)}
    >
      <a href="/professor" className="prof-back-link">
        ← 강의 목록
      </a>

      <PageHeading
        label={`${courseCode(course)} · ${course.section}분반`}
        title={course.title}
        description={`${course.schedule} · ${course.credits}학점`}
      >
        <div className="prof-heading-actions">
          <a href="#students" className="prof-ghost-btn">
            수강생 관리
          </a>
          <a href={`/professor/courses/${course.id}/quizzes`} className="prof-ghost-btn">
            퀴즈 현황
          </a>
          <a href={`/professor/notices?course=${course.id}`} className="quiz-generate-btn">
            강의 자료 관리 →
          </a>
        </div>
      </PageHeading>

      <SummaryCards
        ariaLabel="강의 요약"
        items={[
          { label: '현재 주차', value: course.week, unit: `/${course.totalWeeks}주차` },
          { label: '수강생', value: students.length, unit: `/${course.capacity}명` },
          { label: '평균 진도율', value: avgProgress, unit: '%' },
          {
            label: '승인 대기',
            value: pendingRequests.length,
            unit: '건',
            valueClassName: pendingRequests.length > 0 ? 'prof-text-accent' : undefined,
          },
        ]}
      />

      <div className="prof-dashboard-grid">
        {/* 왼쪽: 진행 현황 + 진도율 분포 */}
        <div className="prof-col">
          <section className="prof-panel">
            <div className="prof-panel-head">
              <h2>진행 현황</h2>
            </div>

            {students.length === 0 ? (
              <p className="prof-empty-text">
                아직 수강생이 없어요. 학생이 수강 신청하면 오른쪽 ‘수강 신청 승인’에 나타나요.
              </p>
            ) : (
              <div className="prof-course-main">
                <div>
                  <div className="course-card-row">
                    <span>평균 진도율</span>
                    <strong>{avgProgress}%</strong>
                  </div>
                  <div className="course-progress-track prof-track-marked">
                    <div className="course-progress-value" style={{ width: `${avgProgress}%` }} />
                    <i
                      className="prof-track-marker"
                      style={{ left: `${weekRate}%` }}
                      title={`수업 진행 ${weekRate}%`}
                    />
                  </div>
                  <p className="prof-hint">세로선은 수업 진행 위치({weekRate}%)예요.</p>
                </div>

                <div className="prof-course-stats">
                  <span>
                    퀴즈 평균 <b>{quizTakers.length > 0 ? `${avgQuiz}%` : '-'}</b>
                  </span>
                  <span>
                    출석 평균 <b>{avgAttendance}%</b>
                  </span>
                </div>
              </div>
            )}
          </section>

          <section className="prof-panel">
            <div className="prof-panel-head">
              <h2>진도율 분포</h2>
              <span className="prof-muted">수강생 {students.length}명</span>
            </div>
            <div className="prof-histogram">
              {BUCKETS.map((b, i) => (
                <div
                  key={b.label}
                  className="prof-histogram-col"
                  tabIndex={bucketCounts[i] > 0 ? 0 : undefined}
                  aria-label={`${b.label} ${bucketCounts[i]}명${
                    bucketCounts[i] > 0
                      ? `: ${bucketStudents[i].map((s) => s.name).join(', ')}`
                      : ''
                  }`}
                >
                  {bucketCounts[i] > 0 && (
                    <div className="prof-histogram-tip" role="tooltip">
                      <strong>
                        {b.label} · {bucketCounts[i]}명
                      </strong>
                      <ul>
                        {bucketStudents[i].slice(0, MAX_TIP).map((s) => (
                          <li key={s.id}>
                            <span>{s.name}</span>
                            <em>{s.progress}%</em>
                          </li>
                        ))}
                      </ul>
                      {bucketCounts[i] > MAX_TIP && <small>외 {bucketCounts[i] - MAX_TIP}명</small>}
                    </div>
                  )}
                  <span className="prof-histogram-count">{bucketCounts[i]}명</span>
                  <div className="prof-histogram-bar-wrap">
                    <div
                      className={`prof-histogram-bar bucket-${i}`}
                      style={{ height: `${(bucketCounts[i] / maxBucket) * 100}%` }}
                    />
                  </div>
                  <span className="prof-histogram-label">{b.label}</span>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* 오른쪽: 승인 · 주의 학생 · 공지 */}
        <div className="prof-col">
          <section className="prof-panel prof-approval-panel">
            <div className="prof-panel-head">
              <h2>수강 신청 승인</h2>
              {pendingRequests.length > 1 && (
                <button type="button" className="prof-small-btn" onClick={approveAll}>
                  모두 승인
                </button>
              )}
            </div>
            {pendingRequests.length === 0 ? (
              <p className="prof-empty-text">대기 중인 신청이 없어요.</p>
            ) : (
              <ul className="prof-list prof-request-list">
                {pendingRequests.map((r) => (
                  <li key={r.id}>
                    <span className="student-profile-avatar prof-mini-avatar">
                      {r.studentName.charAt(0)}
                    </span>
                    <div className="prof-list-main">
                      <strong>
                        {r.studentName} <small>{r.studentNo}</small>
                      </strong>
                      <span>
                        {r.major} · {r.requestedAt}
                      </span>
                      {r.message && <q className="prof-request-message">{r.message}</q>}
                    </div>
                    <div className="prof-request-actions">
                      <button
                        type="button"
                        className="prof-small-btn"
                        onClick={() => approveRequest(r.id)}
                      >
                        승인
                      </button>
                      <button
                        type="button"
                        className="prof-small-btn danger"
                        onClick={() => rejectRequest(r.id)}
                      >
                        거절
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="prof-panel">
            <div className="prof-panel-head">
              <h2>최근 공지·자료</h2>
              <a href={`/professor/notices?course=${course.id}`} className="prof-link">
                작성하기 →
              </a>
            </div>
            {notices.length === 0 ? (
              <p className="prof-empty-text">아직 올린 공지·자료가 없어요.</p>
            ) : (
              <ul className="prof-list">
                {notices.slice(0, 3).map((n) => (
                  <li key={n.id}>
                    <KindBadge kind={n.kind} />
                    <div className="prof-list-main">
                      <strong>{n.title}</strong>
                      <span>
                        {n.createdAt} · 조회 {n.views}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      {/* 수강생 관리 — 검색 · 상태 필터 · 정렬 · CSV · 수강 취소 */}
      <div className="prof-section-gap">
        <StudentManager
          courseId={course.id}
          title={`수강생 관리 (${students.length}명)`}
          onRemove={(s) => {
            if (!confirm(`${s.name}(${s.studentNo}) 학생을 이 강의에서 수강 취소할까요?`)) return
            removeStudent(s.id)
          }}
        />
      </div>
    </PageLayout>
  )
}
