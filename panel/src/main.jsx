import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { SessionProvider } from "./lib/session";

import "./styles/tokens.css";
import "./styles/shell.css";
import "./styles/kit.css";
import "./styles/brand.css";

// Только для локальных снимков экрана (сборка с VITE_DEV_TOKEN_LOGIN=1):
// токен из фрагмента адреса кладётся в хранилище, чтобы безголовый
// браузер открывал панель уже вошедшим. В боевой сборке ветка вырезается.
if (import.meta.env.VITE_DEV_TOKEN_LOGIN === "1") {
  const found = /[#&]token=([^&]+)/.exec(window.location.hash || "");
  const theme = /[#&]theme=(light|dark)/.exec(window.location.hash || "");
  if (theme) localStorage.setItem("vpn_panel_theme", theme[1]);
  if (found) {
    localStorage.setItem("vpn_panel_token", found[1]);
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
}

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
