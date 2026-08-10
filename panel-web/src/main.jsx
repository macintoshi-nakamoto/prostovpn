import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { SessionProvider } from "./lib/session";

import "./styles/tokens.css";
import "./styles/shell.css";
import "./styles/kit.css";

// Панель раздаётся с /admin, а не с корня: корень отдан публичному сайту.
// basename берётся из base сборки, чтобы путь задавался в одном месте —
// в vite.config.js, — и маршруты не разъехались с адресом статики.
const BASENAME = import.meta.env.BASE_URL.replace(/\/$/, "");

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter basename={BASENAME}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
