/**
 * [로그인 상태 훅] 모든 페이지가 '누가 로그인했는지'를 여기서 가져와요. (지금은 개발용 가짜 로그인)
 * - 지금(mock): 기본값이 항상 "로그인된 상태", 로그인 여부만 localStorage 에 저장 (새로고침해도 유지)
 *   사용자 정보는 아래 MOCK_STUDENT / MOCK_PROFESSOR 고정값이에요.
 *
 * TODO(백엔드 연결 시): 이 파일 안쪽만 바꾸면 돼요. 페이지 쪽은 useAuth() 만 쓰고 있어요.
 *   1. 앱 시작 시 api/authApi.ts 의 fetchMe() 로 로그인 사용자 정보를 받아 user 에 넣기
 *      (401 이면 로그아웃 상태 — 서버 세션 쿠키가 로그인 상태를 들고 있어요)
 *   2. localStorage 의 'mock-logged-in' 은 지우기 — 진짜 로그인 정보는 쿠키로만 관리
 *   3. 학생/교수자 구분은 user.role 로 (지금은 useAuth / useProfessorAuth 로 나뉘어 있음)
 */

import { useState } from 'react'
import { logout as logoutRequest } from '../api/authApi'

export interface Student {
  name: string
  email: string
  studentNo?: string // 수강 신청 시 사용
  major?: string
}

const MOCK_STUDENT: Student = {
  name: '김학생',
  email: 'student@example.com',
  studentNo: '20231234',
  major: '컴퓨터공학',
}

const STORAGE_KEY = 'mock-logged-in'

// 저장된 값이 없으면 로그인된 것으로 간주
function readLoggedIn(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'false'
  } catch {
    return true
  }
}

function writeLoggedIn(value: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, String(value))
  } catch {
    // 저장이 막힌 환경(시크릿 모드 등)에서는 무시
  }
}

export function useAuth() {
  const [isLoggedIn, setIsLoggedIn] = useState(readLoggedIn)

  const login = () => {
    writeLoggedIn(true)
    setIsLoggedIn(true)
  }

  const logout = async () => {
    try {
      await logoutRequest() // 서버 세션 종료 (mock 모드에서는 아무것도 안 함)
    } finally {
      writeLoggedIn(false)
      setIsLoggedIn(false)
      // 앱 전체가 로그아웃 상태를 다시 읽도록 첫 화면으로 새로 불러옴
      window.location.href = '/'
    }
  }

  return {
    isLoggedIn,
    user: isLoggedIn ? MOCK_STUDENT : null,
    login,
    logout,
  }
}

/**
 * 로그인한 학생의 학번 (수강목록·챗봇·출석 페이지에서 '내 강의'를 찾을 때 사용)
 * TODO(백엔드): 로그인 응답의 학번 사용
 */
export function useStudentNo() {
  const { user } = useAuth()
  return user?.studentNo ?? user?.email ?? ''
}

/* ---------- 교수자 (mock) ---------- */

export interface Professor {
  name: string
  email: string
  department: string
}

const MOCK_PROFESSOR: Professor = {
  name: '이교수',
  email: 'professor@example.com',
  department: '컴퓨터공학과',
}

/**
 * 교수자 페이지용 mock 로그인 — 로그인 여부는 학생과 같은 키를 공유해요.
 * TODO: 실제 로그인 API가 생기면 user.role === 'professor' 로 구분하도록 합치세요.
 */
export function useProfessorAuth() {
  const { isLoggedIn, login, logout } = useAuth()

  return {
    isLoggedIn,
    user: isLoggedIn ? MOCK_PROFESSOR : null,
    login,
    logout,
  }
}
