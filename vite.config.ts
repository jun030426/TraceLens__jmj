import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 여러 세션이 동시에 dev 서버를 띄울 수 있게 PORT를 존중한다
  server: { port: Number(process.env.PORT) || 5173 },
})
