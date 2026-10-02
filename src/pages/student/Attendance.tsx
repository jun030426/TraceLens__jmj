/**
 * [학생 출석 현황 페이지] 주소: /attendance  (헤더 프로필 메뉴 → 출석 현황)
 * - 토끼 상태(연속 출석/결석) · 출석 요약 · 출석 스탬프 계단 · 강의별 출석률 표
 * - 출석률은 store/courseStore 의 수강 정보(attendance)를 보여줘요. 지금은 임시(mock) 데이터예요.
 * TODO(백엔드): 강의별 출석률 / 주차별 출석 기록 API 연결
 *   예) GET /api/students/me/attendance → [{ courseId, rate, records: [{ week, status }] }]
 */

import { useState } from 'react'
import PageLayout from '../../components/layout/PageLayout'
import PageHeading, { SemesterBadge } from '../../components/common/PageHeading'
import SummaryCards from '../../components/common/SummaryCards'
import CourseTitleCell from '../../components/student/CourseTitleCell'
import AttendanceStairs from '../../components/attendance/AttendanceStairs'
import {
  getRabbitMood,
  MOOD_INFO,
  type AttendanceStreak,
  type RabbitMood,
} from '../../utils/rabbitMood'
import { useStudentNo } from '../../hooks/useAuth'
import { myCoursesOf, useCourseStore } from '../../store/courseStore'
import { accentStyle, courseCode } from '../../utils/course'
import { average } from '../../utils/format'

// 출석률 기준 (필요하면 학교 규정에 맞게 바꾸세요)
const WARN_RATE = 85 // 미만이면 '주의'
const DANGER_RATE = 70 // 미만이면 '위험'

/**
 * 출석한 횟수 (= 스탬프 계단 칸 수)
 * TODO(백엔드): 실제 출석 기록 개수로 교체
 */
// 매개변수 앞 _ : 지금은 안 쓰지만 연결할 때 쓸 값 (주석 해제 시 _ 빼고 rate, week 로)
function attendedCount(_rate: number, _week: number) {
  // ⚠️ 지금은 출석 기록이 하나도 없다고 가정해서 항상 0 (토끼는 출발 칸에 서 있어요)
  return 0

  // TODO(백엔드 연결 후 주석 해제): 실제 출석 횟수로 교체
  // 예) GET /api/students/me/attendance → [{ courseId, attendedCount, ... }]
  // 임시 계산이 필요하면 아래 줄을 쓰면 돼요 (출석률 × 진행 주차)
  // return Math.round((rate / 100) * week)
}

/**
 * 연속 출석 / 연속 결석 일수
 * TODO(백엔드): 실제 값으로 교체 — 예) GET /api/students/me/attendance/streak → { attendStreak, absentStreak }
 */
// ⚠️ 지금은 출석 기록이 하나도 없다고 가정 → 연속 출석 0일, 연속 결석 0일 (기본 토끼)
const MOCK_STREAK: AttendanceStreak = { attendStreak: 0, absentStreak: 0 }

// TODO(백엔드 연결 후 주석 해제): 서버에서 받은 연속 기록으로 교체
// const streak = await fetch('/api/students/me/attendance/streak').then((r) => r.json())
// → { attendStreak: number, absentStreak: number }

/** 개발용 미리보기: 주소 뒤에 ?mood=fire | sleep | cry | happy 를 붙이면 그 상태로 보여요 */
function previewStreak(): AttendanceStreak | null {
  const m = new URLSearchParams(window.location.search).get('mood') as RabbitMood | null
  if (m === 'fire') return { attendStreak: 5, absentStreak: 0 }
  if (m === 'sleep') return { attendStreak: 0, absentStreak: 4 }
  if (m === 'cry') return { attendStreak: 0, absentStreak: 8 }
  if (m === 'happy') return { attendStreak: 1, absentStreak: 0 }
  return null
}

// 수강 강의가 없을 때 계단 칸 수 (한 학기 주차)
const DEFAULT_WEEKS = 15

function rateLevel(rate: number) {
  if (rate < DANGER_RATE) return { label: '위험', cls: 'danger' }
  if (rate < WARN_RATE) return { label: '주의', cls: 'warn' }
  return { label: '양호', cls: 'ok' }
}

export default function Attendance() {
  const db = useCourseStore()
  const rows = myCoursesOf(db, useStudentNo()).sort(
    (a, b) => a.enrollment.attendance - b.enrollment.attendance,
  )

  // 연속 기록 → 토끼 상태
  const streak = previewStreak() ?? MOCK_STREAK
  const mood = getRabbitMood(streak)
  const moodInfo = MOOD_INFO[mood]

  // 스탬프 계단에 보여줄 강의 (기본: 목록 첫 번째)
  const [stairCourseId, setStairCourseId] = useState<number | null>(null)
  const stairRow = rows.find((r) => r.course.id === stairCourseId) ?? rows[0]

  const avg = average(rows.map((r) => r.enrollment.attendance))
  const lowCount = rows.filter((r) => r.enrollment.attendance < WARN_RATE).length

  return (
    <PageLayout role="student">
      <PageHeading
        label="ATTENDANCE"
        title="출석 현황"
        description="수강 중인 강의별 출석률을 확인할 수 있어요."
      >
        <SemesterBadge />
      </PageHeading>

      {/* 토끼 상태 (연속 출석 / 결석) */}
      <section className={`att-mood att-mood-${mood}`} aria-live="polite">
        <img key={mood} src={moodInfo.image} alt="" className="att-mood-img" />
        <div>
          <strong>{moodInfo.title(streak)}</strong>
          <p>{moodInfo.message}</p>
        </div>
      </section>

      <SummaryCards
        className="att-summary"
        ariaLabel="출석 요약"
        items={[
          {
            label: '평균 출석률',
            value: rows.length > 0 ? avg : '-',
            unit: rows.length > 0 ? '%' : undefined,
          },
          { label: '수강 과목', value: rows.length, unit: '과목' },
          {
            label: '출석 주의 과목',
            value: lowCount,
            unit: '과목',
            valueClassName: lowCount > 0 ? 'att-text-warn' : undefined,
          },
        ]}
      />

      {/* 수강 강의가 없어도 계단은 항상 보여줌 (출석 0 → 토끼는 출발 칸) */}
      <section className="att-stairs-panel" aria-label="출석 스탬프 계단">
        <div className="att-stairs-head">
          <div>
            <h2>출석 스탬프 계단</h2>
            <p>출석할 때마다 토끼가 한 칸씩 올라가며 당근을 챙겨요.</p>
          </div>
          {stairRow && rows.length > 1 && (
            <div className="att-course-chips" role="group" aria-label="강의 선택">
              {rows.map(({ course: c }) => (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={c.id === stairRow?.course.id}
                  className={`att-chip course-card-${c.color} ${c.id === stairRow?.course.id ? 'active' : ''}`}
                  style={accentStyle(c)}
                  onClick={() => setStairCourseId(c.id)}
                >
                  {c.title}
                </button>
              ))}
            </div>
          )}
        </div>
        <AttendanceStairs
          attended={
            stairRow ? attendedCount(stairRow.enrollment.attendance, stairRow.course.week) : 0
          }
          total={stairRow?.course.totalWeeks ?? DEFAULT_WEEKS}
          resetKey={stairRow?.course.id ?? 'none'}
          mood={mood}
        />
      </section>

      {rows.length > 0 && (
        <section className="s-list" aria-label="강의별 출석률">
          <div className="s-list-head att-grid" aria-hidden="true">
            <span>강의</span>
            <span>출석률</span>
            <span>진행 주차</span>
            <span>상태</span>
          </div>
          <ul>
            {rows.map(({ course: c, enrollment: e }) => {
              const level = rateLevel(e.attendance)
              return (
                <li
                  key={c.id}
                  className={`s-row att-grid course-card-${c.color}`}
                  style={accentStyle(c)}
                >
                  <CourseTitleCell
                    course={c}
                    meta={`${courseCode(c)} · ${c.professor} · ${c.schedule}`}
                  />
                  <span className="s-cell" data-label="출석률">
                    <span className="s-progress">
                      <span className={`s-bar att-bar ${level.cls}`}>
                        <i style={{ width: `${e.attendance}%` }} />
                      </span>
                      <b>{e.attendance}%</b>
                    </span>
                  </span>
                  <span className="s-cell" data-label="진행 주차">
                    <b>{c.week}</b>/{c.totalWeeks}주
                  </span>
                  <span className="s-cell" data-label="상태">
                    <span className={`att-badge ${level.cls}`}>{level.label}</span>
                  </span>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      <p className="att-hint">
        기준 · 양호 {WARN_RATE}% 이상 / 주의 {DANGER_RATE}~{WARN_RATE - 1}% / 위험 {DANGER_RATE}%
        미만
      </p>
    </PageLayout>
  )
}
