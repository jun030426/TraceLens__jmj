/**
 * [환경 변수 타입] .env 파일의 VITE_ 값들을 TypeScript 가 알 수 있게 선언해요. (.env.example 참고)
 */

/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 주소 앞부분 (기본 '/api') */
  readonly VITE_API_BASE_URL?: string
  /** 'false' 면 실제 서버 호출, 그 외에는 임시(mock) 데이터 */
  readonly VITE_USE_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
