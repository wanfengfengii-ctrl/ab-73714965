import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // 本地开发时把 API 请求代理到本机后端
    proxy: { "/api": "http://localhost:8000" },
  },
  preview: {
    // 本地预览（vite preview）同样代理，便于端到端自测
    proxy: { "/api": "http://localhost:8000" },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
