/**
 * [교수자 공용 컴포넌트] 수강생 표 — 검색 · 상태 필터(우수/주의/위험) · 정렬 · (선택) 수강 취소
 * - 교수자 수강생 관리(ProfessorStudents), 강의 상세(ProfessorCourseDetail)에서 사용
 * - downloadCsv: 수강생 목록을 엑셀용 CSV 파일로 내려받기
 */

import { useMemo, useState } from 'react'
import EmptyState from '../common/EmptyState'
import SegmentButtons from '../common/SegmentButtons'
import { courseById, useCourseStore } from '../../store/courseStore'
import { accentStyle, statusClass, studentStatus } from '../../utils/course'
import type { EnrolledStudent, StudentStatus } from '../../types/course'

type SortKey = 'name' | 'progress' | 'quizAvg' | 'attendance'
type StatusFilter = '전체' | StudentStatus

const STATUS_FILTERS: StatusFilter[] = ['전체', '우수', '주의', '위험']

const SORT_LABEL: Record<SortKey, string> = {
  name: '이름',
  progress: '진도율',
  quizAvg: '퀴즈',
  attendance: '출석률',
}

/** 수강생 목록을 CSV 파일로 저장 (TODO: 서버에서 파일을 만들어 주면 그 주소로 바꿔도 돼요) */
export function downloadCsv(rows: EnrolledStudent[]) {
  const header = [
    '강의',
    '이름',
    '학번',
    '전공',
    '팀',
    '진도율',
    '퀴즈평균',
    '출석률',
    '상태',
    '최근접속',
  ]
  const lines = rows.map((s) =>
    [
      courseById(s.courseId)?.title ?? '',
      s.name,
      s.studentNo,
      s.major,
      s.team ?? '',
      s.progress,
      s.quizAvg || '',
      s.attendance,
      studentStatus(s),
      s.lastActive,
    ].join(','),
  )
  // 엑셀에서 한글이 깨지지 않도록 BOM 추가
  const blob = new Blob(['﻿' + [header.join(','), ...lines].join('\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '수강생목록.csv'
  a.click()
  URL.revokeObjectURL(url)
}

interface StudentManagerProps {
  /** null 이면 전체 강의 수강생 */
  courseId: number | null
  /** 패널 제목 — 있으면 제목 줄과 CSV 버튼을 같이 보여줌 */
  title?: string
  /** 있으면 각 행에 '수강 취소' 버튼을 보여줌 */
  onRemove?: (student: EnrolledStudent) => void
}

export default function StudentManager({ courseId, title, onRemove }: StudentManagerProps) {
  const { students } = useCourseStore()
  const inCourse = courseId === null ? students : students.filter((s) => s.courseId === courseId)

  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<StatusFilter>('전체')
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortAsc, setSortAsc] = useState(true)

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = inCourse.filter(
      (s) =>
        (status === '전체' || studentStatus(s) === status) &&
        (q === '' ||
          s.name.toLowerCase().includes(q) ||
          s.studentNo.includes(q) ||
          s.major.toLowerCase().includes(q)),
    )
    return [...filtered].sort((a, b) => {
      const diff = sortKey === 'name' ? a.name.localeCompare(b.name, 'ko') : a[sortKey] - b[sortKey]
      return sortAsc ? diff : -diff
    })
  }, [inCourse, query, status, sortKey, sortAsc])

  const hasTeams = inCourse.some((s) => s.team)
  const counts = {
    우수: inCourse.filter((s) => studentStatus(s) === '우수').length,
    주의: inCourse.filter((s) => studentStatus(s) === '주의').length,
    위험: inCourse.filter((s) => studentStatus(s) === '위험').length,
  }

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc((v) => !v)
    else {
      setSortKey(key)
      setSortAsc(key === 'name')
    }
  }

  const sortTh = (k: SortKey) => (
    <th key={k} aria-sort={sortKey === k ? (sortAsc ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="prof-sort" onClick={() => toggleSort(k)}>
        {SORT_LABEL[k]}
        <span>{sortKey === k ? (sortAsc ? '▲' : '▼') : '↕'}</span>
      </button>
    </th>
  )

  const searchInput = (
    <input
      type="search"
      className="prof-input prof-search"
      placeholder="이름, 학번, 전공으로 검색"
      value={query}
      onChange={(e) => setQuery(e.target.value)}
      aria-label="수강생 검색"
    />
  )

  return (
    <section className="prof-panel" id="students">
      {title && (
        <div className="prof-panel-head prof-panel-head-search">
          <h2>{title}</h2>
          {searchInput}
        </div>
      )}
      <div className="prof-toolbar">
        {/* 제목 줄이 없을 때(전체 수강생 페이지)는 검색칸을 여기에 둠 */}
        {!title && searchInput}
        <SegmentButtons
          ariaLabel="상태 필터"
          options={STATUS_FILTERS}
          value={status}
          onChange={setStatus}
          renderLabel={(s) => (
            <>
              {s}
              {s !== '전체' && <em>{counts[s]}</em>}
            </>
          )}
        />
      </div>

      {rows.length === 0 ? (
        <EmptyState
          className="prof-empty-inline"
          icon="?"
          title="조건에 맞는 학생이 없어요"
          description="검색어나 필터를 바꿔보세요."
        />
      ) : (
        <div className="prof-table-wrap">
          <table className="prof-table">
            <thead>
              <tr>
                {sortTh('name')}
                <th>학번 · 전공</th>
                {courseId === null && <th>강의</th>}
                {hasTeams && <th>팀</th>}
                {sortTh('progress')}
                {sortTh('quizAvg')}
                {sortTh('attendance')}
                <th>최근 접속</th>
                <th>상태</th>
                {onRemove && <th aria-label="관리" />}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const st = studentStatus(s)
                const course = courseById(s.courseId)
                return (
                  <tr key={s.id}>
                    <td>
                      <div className="prof-cell-name">
                        <span className="student-profile-avatar prof-mini-avatar">
                          {s.name.charAt(0)}
                        </span>
                        <strong>{s.name}</strong>
                      </div>
                    </td>
                    <td className="prof-muted">
                      {s.studentNo}
                      <br />
                      {s.major}
                    </td>
                    {courseId === null && (
                      <td>
                        <span
                          className={`quiz-card-course prof-course-chip quiz-card-${course?.color}`}
                          style={accentStyle(course)}
                        >
                          {course?.title}
                        </span>
                      </td>
                    )}
                    {hasTeams && <td>{s.team ?? '-'}</td>}
                    <td>
                      <div
                        className={`prof-cell-bar course-card-${course?.color}`}
                        style={accentStyle(course)}
                      >
                        <div className="course-progress-track">
                          <div
                            className="course-progress-value"
                            style={{ width: `${s.progress}%` }}
                          />
                        </div>
                        <span>{s.progress}%</span>
                      </div>
                    </td>
                    <td>{s.quizAvg > 0 ? `${s.quizAvg}%` : '-'}</td>
                    <td className={s.attendance < 80 ? 'prof-text-danger' : undefined}>
                      {s.attendance}%
                    </td>
                    <td className="prof-muted">{s.lastActive}</td>
                    <td>
                      <span className={`prof-status ${statusClass[st]}`}>{st}</span>
                    </td>
                    {onRemove && (
                      <td>
                        <button
                          type="button"
                          className="prof-small-btn danger"
                          onClick={() => onRemove(s)}
                        >
                          수강 취소
                        </button>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="prof-hint">
        상태 기준 · 위험: 진도율 30% 미만 또는 출석 70% 미만 / 주의: 진도율 50% 미만, 출석 85% 미만,
        퀴즈 60% 미만
      </p>
    </section>
  )
}
