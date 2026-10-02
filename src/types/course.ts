/**
 * [공용 타입] 강의 · 수강생 · 수강 신청 · 공지 데이터 모양
 * - 학생/교수자 화면과 store/courseStore.ts, api/courseApi.ts 가 함께 써요.
 * - 백엔드 API 응답도 이 모양에 맞춰 주면 화면 코드를 고칠 필요가 없어요.
 */

/** 기본 카드 색상 5개 + 직접 고른 색('custom') */
export type AccentColor = 'purple' | 'blue' | 'green' | 'orange' | 'pink' | 'custom'

/** 강의 */
export interface ProfessorCourse {
  id: number
  title: string
  courseNo: string // 강의 번호 — 숫자 6자리 (예: 302110)
  section: string // 분반 '01' ~ '03'
  professor: string
  description?: string
  capacity: number // 정원
  credits: number
  schedule: string
  color: AccentColor
  customColor?: string // color 가 'custom' 일 때 사용하는 hex 값
  week: number // 현재 진행 주차
  totalWeeks: number
}

export type StudentStatus = '우수' | '주의' | '위험'

/** 강의에 등록된(승인된) 수강생 */
export interface EnrolledStudent {
  id: number
  courseId: number
  name: string
  studentNo: string
  major: string
  team?: string
  progress: number // 진도율 0~100
  quizAvg: number // 퀴즈 평균 정답률 0~100
  attendance: number // 출석률 0~100
  lastActive: string
}

export type RequestStatus = '대기' | '승인' | '거절'

/** 학생이 보낸 수강 신청 */
export interface EnrollmentRequest {
  id: number
  courseId: number
  studentName: string
  studentNo: string
  major: string
  email?: string
  message?: string
  requestedAt: string
  status: RequestStatus
  decidedAt?: string
}

export type NoticeKind = '공지' | '자료'

/** 교수자가 올리는 공지 · 강의자료 */
export interface Notice {
  id: number
  courseId: number
  kind: NoticeKind
  title: string
  body: string
  createdAt: string
  pinned: boolean
  files: { name: string; size: number }[]
  views: number
}

/** 교수자 '강의 추가' 모달에서 입력받는 값 */
export interface NewCourseInput {
  title: string
  courseNo: string
  section: string
  professor: string
  description?: string
  capacity: number
  credits: number
  schedule: string
  color: AccentColor
  customColor?: string
  totalWeeks: number
}

/** 학생 화면에서 보는 강의별 수강 신청 상태 */
export type EnrollmentState = '신청 가능' | '승인 대기' | '수강 중' | '거절됨' | '정원 마감'

/** 수강 신청 시 보내는 값 */
export interface EnrollmentInput {
  courseId: number
  studentName: string
  studentNo: string
  major: string
  email?: string
  message?: string
}
