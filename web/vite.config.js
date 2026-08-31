import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        // Локальной панели обычно нет под рукой, поэтому по умолчанию
        // ходим в боевую — так кабинет открывается с настоящими данными.
        // Свой бэкенд подставляется через PANEL_PROXY.
        target: process.env.PANEL_PROXY || "https://prostovpn.cc",
        changeOrigin: true,
        secure: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
