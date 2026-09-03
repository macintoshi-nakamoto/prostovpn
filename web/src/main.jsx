import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import "./styles/base.css";

import { SessionProvider } from "./lib/session.jsx";
import { I18nProvider } from "./lib/i18n/index.jsx";
import { ThemeProvider } from "./lib/theme.jsx";
import { App } from "./App.jsx";

// Обличье мини-приложения Telegram. Грузится последним намеренно: все его
// правила должны перекрывать стили страниц. Вне Telegram файл спит.
import "./styles/tma.css";
// Обличье второго бренда (Rus VPN). Живёт под html.brand-rusvpn — сборке
// Prosto ничего не меняет, поэтому подключается всегда и последним.
import "./styles/brand-rusvpn.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <BrowserRouter>
          <SessionProvider>
            <App />
          </SessionProvider>
        </BrowserRouter>
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
);
