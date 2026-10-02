/**
 * [서버 연결] 강의 · 수강 신청 API — 우리 백엔드 서버의 /api/... 주소를 불러요.
 *
 * 지금 화면은 store/courseStore.ts 의 임시(mock) 데이터로 동작해요.
 * 서버가 준비되면 courseStore.ts 안쪽에서 아래 함수들을 부르도록 바꾸면 돼요.
 * (화면 코드는 courseStore 의 함수만 쓰고 있어서 고칠 필요 없어요)
 *
 * 주소·응답 모양은 '예시'예요. 백엔드에서 정한 주소와 다르면 여기만 고치면 돼요.
 * 응답 데이터 모양은 types/course.ts 의 타입에 맞춰 주세요.
 * '나(me)'가 누구인지는 백엔드가 로그인 세션 쿠키로 판단해요. (api/client.ts 참고)
 *
 * 화면 흐름
 *  1. 교수자: 강의 추가                       → createCourse
 *  2. 학생: 개설된 강의 목록 보기              → fetchCourses
 *  3. 학생: 수강 신청 / 신청 취소              → requestEnrollment / cancelEnrollment
 *  4. 교수자: 신청 목록 보기 · 승인 · 거절      → fetchEnrollmentRequests / decideEnrollment
 *  5. 학생: 내 강의(승인된 강의) 보기           → fetchMyCourses
 *  6. 교수자: 수강생 목록 · 수강 취소           → fetchCourseStudents / removeStudent
 */

import { apiFetch } from './client'
import type {
  EnrolledStudent,
  EnrollmentRequest,
  NewCourseInput,
  ProfessorCourse,
} from '../types/course'

/* ---------- 강의 ---------- */

/** 개설된 강의 전체 (학생 수강 신청 목록 · 교수자 담당 강의) */
export const fetchCourses = () => apiFetch<ProfessorCourse[]>('/courses')

/** 교수자 강의 추가 → 만들어진 강의(id 포함)를 돌려줌 */
export const createCourse = (input: NewCourseInput) =>
  apiFetch<ProfessorCourse>('/courses', { method: 'POST', body: input })

/* ---------- 학생 ---------- */

/** 내가 수강 중인 강의 (승인된 것) */
export const fetchMyCourses = () =>
  apiFetch<{ course: ProfessorCourse; enrollment: EnrolledStudent }[]>('/students/me/courses')

/** 수강 신청 */
export const requestEnrollment = (courseId: number, message?: string) =>
  apiFetch(`/courses/${courseId}/enrollments`, { method: 'POST', body: { message } })

/** 대기 중인 수강 신청 취소 */
export const cancelEnrollment = (courseId: number) =>
  apiFetch(`/courses/${courseId}/enrollments/me`, { method: 'DELETE' })

/* ---------- 교수자 ---------- */

/** 강의별 승인 대기 중인 수강 신청 목록 */
export const fetchEnrollmentRequests = (courseId: number) =>
  apiFetch<EnrollmentRequest[]>(`/courses/${courseId}/enrollments?status=PENDING`)

/** 수강 신청 승인 / 거절 */
export const decideEnrollment = (requestId: number, status: 'APPROVED' | 'REJECTED') =>
  apiFetch(`/enrollments/${requestId}`, { method: 'PATCH', body: { status } })

/** 강의 수강생 목록 */
export const fetchCourseStudents = (courseId: number) =>
  apiFetch<EnrolledStudent[]>(`/courses/${courseId}/students`)

/** 수강생 수강 취소 */
export const removeStudent = (courseId: number, studentId: number) =>
  apiFetch(`/courses/${courseId}/students/${studentId}`, { method: 'DELETE' })
