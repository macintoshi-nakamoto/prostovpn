import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Публичный сайт: лендинг, вход, регистрация и личный кабинет. Живёт в корне
// (в отличие от админ-панели на /admin), поэтому base не переопределяем.
//
// В разработке /api проксируется на бэкенд, чтобы в коде остались
// относительные пути и не понадобился обход CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
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
