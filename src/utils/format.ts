/**
 * [공용 유틸] 숫자 · 날짜 · 파일 크기 계산/표시 함수
 * - 여러 페이지에서 같이 쓰는 작은 함수 모음이에요.
 */

/** 평균 (반올림, 빈 배열이면 0) */
export const average = (values: number[]) =>
  values.length === 0 ? 0 : Math.round(values.reduce((sum, v) => sum + v, 0) / values.length)

/** 비율(%) — part / total × 100 (반올림, total 이 0이면 0) */
export const percent = (part: number, total: number) =>
  total === 0 ? 0 : Math.round((part / total) * 100)

/** 파일 크기 표시 (예: 4.8MB) */
export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

const pad = (n: number) => String(n).padStart(2, '0')

/** 오늘 날짜 'YYYY.MM.DD' */
export function todayString() {
  const d = new Date()
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}`
}

/** 지금 시각 'YYYY.MM.DD HH:mm' */
export function nowString() {
  const d = new Date()
  return `${todayString()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
