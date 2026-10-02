/**
 * [공용 유틸] 강의 관련 계산 · 표시 함수
 * - 강의 카드 색상(accentStyle), 수업 진행률, 수강생 학습 상태(우수/주의/위험) 판단
 */

import type { CSSProperties } from 'react'
import type { AccentColor, EnrolledStudent, ProfessorCourse, StudentStatus } from '../types/course'
import { percent } from './format'

/** 기본 카드 색상 목록 (강의 추가 모달에서 사용) */
export const PRESET_COLORS: {
  value: Exclude<AccentColor, 'custom'>
  label: string
  hex: string
}[] = [
  { value: 'purple', label: '보라', hex: '#5145f5' },
  { value: 'blue', label: '파랑', hex: '#3b82f6' },
  { value: 'green', label: '초록', hex: '#16a36a' },
  { value: 'orange', label: '주황', hex: '#e8850c' },
  { value: 'pink', label: '분홍', hex: '#e0457b' },
]

/** hex 색을 흰색과 섞어서 연한 배경색을 만들어요 (ratio: 원래 색 비율) */
function tint(hex: string, ratio = 0.12) {
  const n = parseInt(hex.replace('#', ''), 16)
  const mix = (c: number) => Math.round(c * ratio + 255 * (1 - ratio))
  return `rgb(${mix((n >> 16) & 255)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`
}

/**
 * 직접 고른 색(custom)일 때 카드에 넣을 style
 * - 기본 색은 CSS 클래스(course-card-purple 등)가 처리하므로 undefined
 */
export function accentStyle(c?: {
  color: AccentColor
  customColor?: string
}): CSSProperties | undefined {
  if (!c || c.color !== 'custom' || !c.customColor) return undefined
  return {
    '--accent': c.customColor,
    '--accent-soft': tint(c.customColor),
  } as CSSProperties
}

/** 강의 번호 표시 (예: 302110-01) */
export const courseCode = (c: ProfessorCourse) => `${c.courseNo}-${c.section}`

/** 수업 진행률(%) — 현재 주차 / 전체 주차 */
export const weekRate = (c: ProfessorCourse) => Math.min(100, percent(c.week, c.totalWeeks))

/** 진도율·퀴즈·출석으로 학습 상태 판단 (기준은 필요에 맞게 조정) */
export function studentStatus(s: EnrolledStudent): StudentStatus {
  if (s.progress < 30 || s.attendance < 70) return '위험'
  if (s.progress < 50 || s.attendance < 85 || (s.quizAvg > 0 && s.quizAvg < 60)) return '주의'
  return '우수'
}

/** 상태별 CSS 클래스 */
export const statusClass: Record<StudentStatus, string> = {
  우수: 'ok',
  주의: 'warn',
  위험: 'danger',
}
