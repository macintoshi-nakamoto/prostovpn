import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const here = fileURLToPath(new URL(".", import.meta.url));

// Публичный сайт: лендинг, вход, регистрация и личный кабинет. Живёт в корне
// (в отличие от админ-панели на /admin), поэтому base не переопределяем.
//
// Два бренда из одного кода: режим сборки выбирает .env.<mode>, а бренд —
// каталог сборки (dist для Prosto, dist-rusvpn для Rus VPN), чтобы обе
// сборки лежали рядом и раздавались разными доменами.
//
// В разработке /api проксируется на бэкенд, чтобы в коде остались
// относительные пути и не понадобился обход CORS. DEV_API в .env.local
// переключает прокси на боевой сервер, когда локального бэкенда нет.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, here, "");
  const brand = env.VITE_BRAND || "prosto";
  return {
    plugins: [react()],
    server: {
      port: 5174,
      proxy: {
        "/api": {
          target: env.DEV_API || "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: brand === "prosto" ? "dist" : `dist-${brand}`,
      sourcemap: false,
    },
  };
});
