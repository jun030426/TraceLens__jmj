/**
 * [서버 통신 공용 함수] 프론트엔드 → 우리 백엔드 서버 요청은 모두 이 파일의 apiFetch 를 거쳐요.
 *
 * ─────────────────────────────────────────────────────────────────────
 *  전체 구조 (외부 AI 회사의 API key 를 쓰는 방식이 아니에요)
 *
 *    [브라우저 · 이 프론트엔드]
 *          │  fetch('/api/...')   ← 프론트는 우리 백엔드만 불러요
 *          ▼
 *    [우리 백엔드 서버]  로그인 · 강의 · 수강 · 퀴즈 · 공지 · DB
 *          │  서버 내부 통신 (프론트는 이 주소를 몰라도 돼요)
 *          ▼
 *    [우리 AI 서버(직접 띄운 모델)]  챗봇 답변 · AI 퀴즈 생성 · 강의자료 분석
 *
 *  - 프론트엔드는 AI 서버를 직접 부르지 않아요. AI 기능도 전부 백엔드의 /api/... 를 통해요.
 *  - AI 서버 주소, DB 비밀번호 같은 비밀 값은 백엔드에만 두세요.
 *    ⚠️ VITE_ 로 시작하는 환경 변수는 빌드 결과(브라우저)에 그대로 노출돼요 → 비밀 값 넣지 말 것!
 *  - 로그인 상태는 백엔드가 세션 쿠키(또는 httpOnly 쿠키 토큰)로 관리한다고 가정해요.
 *    그래서 요청마다 credentials: 'include' 로 쿠키를 같이 보내고, 프론트는 토큰을 저장하지 않아요.
 * ─────────────────────────────────────────────────────────────────────
 *
 * 설정 (프로젝트 루트의 .env 파일 — .env.example 참고)
 *  - VITE_API_BASE_URL : API 주소 앞부분. 기본 '/api' (같은 도메인, 개발 중에는 vite.config.ts 프록시가 전달)
 *  - VITE_USE_MOCK     : 'false' 로 바꾸면 임시 데이터 대신 실제 서버를 불러요. (기본: 임시 데이터)
 */

/** API 주소 앞부분 (예: '/api' → fetch('/api/courses')) */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/+$/, '')

/**
 * true  = 서버 없이 화면 확인용 임시(mock) 데이터 사용
 * false = 실제 백엔드 서버 호출
 */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

/** 서버가 오류 응답을 줬을 때 던지는 에러 (status 로 401/403/404 등을 구분할 수 있어요) */
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface ApiFetchOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** JSON 으로 보낼 값 */
  body?: unknown
  /** 파일 업로드할 때 (multipart/form-data) — body 대신 사용 */
  formData?: FormData
  /** 요청 취소용 (페이지를 벗어날 때 등) */
  signal?: AbortSignal
}

/**
 * 백엔드 API 호출
 * @example const courses = await apiFetch<ProfessorCourse[]>('/courses')
 * @example await apiFetch('/courses', { method: 'POST', body: input })
 *
 * 서버 응답 약속
 *  - 성공: 2xx + JSON 본문 (본문이 없으면 204)
 *  - 실패: 4xx/5xx + { "message": "사용자에게 보여줄 오류 문구" } (없으면 기본 문구 사용)
 */
export async function apiFetch<T = void>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { method = 'GET', body, formData, signal } = options

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    credentials: 'include', // 로그인 세션 쿠키를 같이 보냄
    // FormData 는 브라우저가 Content-Type(boundary 포함)을 직접 정하므로 지정하지 않아요
    headers: formData ? undefined : { 'Content-Type': 'application/json' },
    body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
    signal,
  })

  if (!res.ok) {
    // 로그인이 풀린 경우 → 로그인 화면으로
    if (res.status === 401 && window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, data?.message ?? `요청에 실패했어요. (${res.status})`)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** 임시(mock) 모드에서 서버 응답처럼 잠깐 기다렸다가 값을 돌려줘요 */
export function mockDelay<T>(value: T, ms = 400): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms))
}
