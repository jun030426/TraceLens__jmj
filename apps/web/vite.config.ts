import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: process.env.LERNY_API_PROXY_TARGET || "http://127.0.0.1:8000" } },
  },
});
