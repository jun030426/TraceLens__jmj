/**
 * [Vite 설정] 개발 서버 · 빌드 설정
 *
 * 개발 중 프록시: `npm run dev` 로 띄운 화면(http://localhost:5173)에서 /api 로 보내는 요청을
 * 우리 백엔드 서버(기본 http://localhost:8080)로 넘겨줘요. → 개발 중 CORS 설정 없이 바로 연결 가능
 * 백엔드 주소가 다르면 .env 의 DEV_API_PROXY_TARGET 을 바꾸세요. (.env.example 참고)
 */

import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: env.DEV_API_PROXY_TARGET || 'http://localhost:8080',
          changeOrigin: true,
        },
      },
    },
  }
})
