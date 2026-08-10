import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке панель живёт на 5173, а бэкенд — на 8000. Проксируем /api,
// чтобы в коде остались относительные пути и не понадобился CORS-обход.
//
// base: "/admin/" — корень сайта занят публичными страницами, панель
// переехала на отдельный путь. Перед ним на боевом сервере стоит фильтр по
// адресам (см. deploy/nginx.conf): пускать в админку весь интернет незачем,
// а отделить её от сайта одним префиксом дешевле, чем поднимать поддомен.
export default defineConfig({
  base: "/admin/",
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
