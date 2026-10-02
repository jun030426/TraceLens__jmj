/**
 * [서버 연결] 로그인 · 로그아웃 · 회원가입 API — 로그인/회원가입 페이지, hooks/useAuth.ts 에서 사용
 *
 * 로그인 방식(가정): 백엔드가 로그인 성공 시 세션 쿠키(또는 httpOnly 쿠키 토큰)를 내려주고,
 *   이후 모든 /api 요청은 그 쿠키로 '누가 요청했는지' 판단해요.
 *   → 프론트는 비밀번호·토큰을 localStorage 에 저장하지 않아요. (보안상 저장하면 안 돼요)
 *
 * 요청/응답 약속 (예시 — 백엔드와 맞춰서 바꾸세요)
 *   POST /api/auth/login   { userId, password }  → LoginUser
 *   POST /api/auth/logout                        → 204
 *   POST /api/auth/signup  SignupInput           → 201
 *   GET  /api/auth/me                            → LoginUser (로그인 안 됐으면 401)
 */

import { apiFetch, mockDelay, USE_MOCK } from './client'

export type UserRole = 'student' | 'professor'

/** 로그인한 사용자 정보 (서버 응답) */
export interface LoginUser {
  role: UserRole
  name: string
  email: string
  /** 학생: 학번 */
  studentNo?: string
  /** 학생: 전공 / 교수자: 소속 학과 */
  major?: string
  department?: string
}

export interface SignupInput {
  role: UserRole
  name: string
  /** 학생은 학번, 교수자는 교수자 아이디 */
  userId: string
  school: string
  major: string
  password: string
  email: string
  phone: string
}

/** 로그인 — 실패하면 ApiError(401 등)를 던져요 */
export async function login(userId: string, password: string): Promise<LoginUser> {
  if (USE_MOCK) {
    // 임시: 숫자로만 된 아이디 = 학번 → 학생, 그 외 → 교수자
    const role: UserRole = /^\d+$/.test(userId) ? 'student' : 'professor'
    return mockDelay({ role, name: role === 'student' ? '김학생' : '이교수', email: '' }, 300)
  }
  return apiFetch<LoginUser>('/auth/login', { method: 'POST', body: { userId, password } })
}

/** 로그아웃 — 서버 세션 종료 */
export async function logout(): Promise<void> {
  if (USE_MOCK) return
  await apiFetch('/auth/logout', { method: 'POST' })
}

/** 회원가입 */
export async function signup(input: SignupInput): Promise<void> {
  if (USE_MOCK) {
    await mockDelay(null, 300)
    return
  }
  await apiFetch('/auth/signup', { method: 'POST', body: input })
}

/** 지금 로그인한 사용자 (새로고침 후 로그인 상태 확인용) */
export const fetchMe = () => apiFetch<LoginUser>('/auth/me')
