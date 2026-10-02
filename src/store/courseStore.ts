/**
 * [데이터 저장소] 강의 · 수강생 · 수강 신청 — 학생/교수자 화면이 함께 쓰는 개발용 mock 저장소
 *
 * - localStorage 에 저장돼서 새로고침해도 유지돼요.
 * - 학생 화면과 교수자 화면을 다른 탭에 띄워도 바로 반영돼요 (storage 이벤트).
 * - 화면 코드는 useCourseStore() 와 아래 함수들만 쓰므로,
 *   백엔드가 생기면 이 파일 안쪽만 api/courseApi.ts 호출로 바꾸면 돼요.
 *   (바꾸는 방법 예: 앱 시작 시 fetchCourses() 등으로 state 를 채우고, 각 함수는 API 호출 성공 후
 *    setState 로 화면 값만 갱신 — localStorage 저장 부분은 삭제. api/client.ts 의 USE_MOCK 으로 분기해도 돼요)
 *     addCourse          → POST   /api/courses
 *     requestEnrollment  → POST   /api/courses/:id/enrollments
 *     cancelRequest      → DELETE /api/courses/:courseId/enrollments/me
 *     approveRequest     → PATCH  /api/enrollments/:id { status: 'APPROVED' }
 *     rejectRequest      → PATCH  /api/enrollments/:id { status: 'REJECTED' }
 *     removeStudent      → DELETE /api/courses/:courseId/students/:id
 */

import { useSyncExternalStore } from 'react'
import { seedCourses, seedRequests, seedStudents } from '../mock/courseSeed'
import { nowString } from '../utils/format'
import type {
  EnrolledStudent,
  EnrollmentInput,
  EnrollmentRequest,
  EnrollmentState,
  NewCourseInput,
  ProfessorCourse,
} from '../types/course'

export interface MockDb {
  courses: ProfessorCourse[]
  students: EnrolledStudent[]
  requests: EnrollmentRequest[]
}

// v4: 강의 번호(숫자 6자리)·분반('01'~'03') 추가, 분야·강의실 제거 — 이전 저장 데이터와 구조가 달라 키를 바꿈
const STORAGE_KEY = 'lerny-mock-db-v4'

const seed = (): MockDb => ({
  courses: seedCourses,
  students: seedStudents,
  requests: seedRequests,
})

function load(): MockDb {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as MockDb
  } catch {
    // 저장이 막힌 환경이면 seed 로 시작
  }
  return seed()
}

let state: MockDb = load()
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((l) => l())
}

function setState(updater: (prev: MockDb) => MockDb) {
  state = updater(state)
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 무시
  }
  emit()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

// 다른 탭(예: 학생 화면)에서 바뀐 내용 반영
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY) {
      state = load()
      emit()
    }
  })
}

const nextId = (list: { id: number }[]) => Math.max(0, ...list.map((x) => x.id)) + 1

/* ---------- 읽기 ---------- */

/** 컴포넌트에서 쓰는 훅 — 값이 바뀌면 화면이 다시 그려져요 */
export function useCourseStore() {
  return useSyncExternalStore(subscribe, () => state)
}

export const courseById = (id: number) => state.courses.find((c) => c.id === id)

/** 강의 하나의 수강생 목록 */
export const studentsOf = (db: MockDb, courseId: number) =>
  db.students.filter((s) => s.courseId === courseId)

/** 강의 하나의 승인 대기 중인 신청 목록 */
export const pendingRequestsOf = (db: MockDb, courseId: number) =>
  db.requests.filter((r) => r.courseId === courseId && r.status === '대기')

/**
 * 학생이 수강 중인(승인된) 강의 목록 — 수강목록 · 챗봇 · 출석 페이지에서 사용
 * TODO(백엔드): GET /api/students/me/courses
 */
export function myCoursesOf(db: MockDb, studentNo: string) {
  return db.students
    .filter((s) => s.studentNo === studentNo)
    .flatMap((enrollment) => {
      const course = db.courses.find((c) => c.id === enrollment.courseId)
      return course ? [{ enrollment, course }] : []
    })
}

/* ---------- 강의 ---------- */

export function addCourse(input: NewCourseInput): ProfessorCourse {
  const course: ProfessorCourse = { ...input, id: nextId(state.courses), week: 1 }
  setState((s) => ({ ...s, courses: [...s.courses, course] }))
  return course
}

/* ---------- 수강 신청 ---------- */

/** 학생 화면에서 버튼 상태를 정할 때 사용 */
export function enrollmentStateOf(
  db: MockDb,
  courseId: number,
  studentNo: string,
): EnrollmentState {
  if (db.students.some((s) => s.courseId === courseId && s.studentNo === studentNo))
    return '수강 중'
  const last = [...db.requests]
    .reverse()
    .find((r) => r.courseId === courseId && r.studentNo === studentNo)
  if (last?.status === '대기') return '승인 대기'
  const course = db.courses.find((c) => c.id === courseId)
  if (course && studentsOf(db, courseId).length >= course.capacity) return '정원 마감'
  if (last?.status === '거절') return '거절됨'
  return '신청 가능'
}

export function requestEnrollment(
  input: EnrollmentInput,
): { ok: true } | { ok: false; reason: string } {
  const current = enrollmentStateOf(state, input.courseId, input.studentNo)
  if (current === '수강 중') return { ok: false, reason: '이미 수강 중인 강의예요.' }
  if (current === '승인 대기')
    return { ok: false, reason: '이미 신청했어요. 교수님 승인을 기다려 주세요.' }
  if (current === '정원 마감') return { ok: false, reason: '정원이 가득 찼어요.' }

  setState((s) => ({
    ...s,
    requests: [
      ...s.requests,
      {
        ...input,
        message: input.message?.trim() || undefined,
        id: nextId(s.requests),
        requestedAt: nowString(),
        status: '대기',
      },
    ],
  }))
  return { ok: true }
}

/** 학생이 대기 중인 신청을 취소 */
export function cancelRequest(courseId: number, studentNo: string) {
  setState((s) => ({
    ...s,
    requests: s.requests.filter(
      (r) => !(r.courseId === courseId && r.studentNo === studentNo && r.status === '대기'),
    ),
  }))
}

export function approveRequest(requestId: number) {
  setState((s) => {
    const req = s.requests.find((r) => r.id === requestId)
    if (!req || req.status !== '대기') return s

    const alreadyIn = s.students.some(
      (st) => st.courseId === req.courseId && st.studentNo === req.studentNo,
    )
    const newStudent: EnrolledStudent = {
      id: nextId(s.students),
      courseId: req.courseId,
      name: req.studentName,
      studentNo: req.studentNo,
      major: req.major,
      progress: 0,
      quizAvg: 0,
      attendance: 100,
      lastActive: '-',
    }

    return {
      ...s,
      students: alreadyIn ? s.students : [...s.students, newStudent],
      requests: s.requests.map((r) =>
        r.id === requestId ? { ...r, status: '승인', decidedAt: nowString() } : r,
      ),
    }
  })
}

export function rejectRequest(requestId: number) {
  setState((s) => ({
    ...s,
    requests: s.requests.map((r) =>
      r.id === requestId && r.status === '대기'
        ? { ...r, status: '거절', decidedAt: nowString() }
        : r,
    ),
  }))
}

/** 교수자가 수강생을 강의에서 뺌 (수강 취소) */
export function removeStudent(studentId: number) {
  setState((s) => ({ ...s, students: s.students.filter((st) => st.id !== studentId) }))
}
