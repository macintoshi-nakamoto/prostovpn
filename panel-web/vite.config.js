import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке панель живёт на 5173, а бэкенд — на 8000. Проксируем /api,
// чтобы в коде остались относительные пути и не понадобился CORS-обход.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
