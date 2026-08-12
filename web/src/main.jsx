import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

// Базовые стили — первым импортом, до компонентов: в сборку css попадает в
// порядке импортов, и при равной специфичности побеждает тот, что ниже.
// Компонент должен уточнять базу, а не наоборот.
import "./styles/base.css";

import { SessionProvider } from "./lib/session.jsx";
import { I18nProvider } from "./lib/i18n/index.jsx";
import { ThemeProvider } from "./lib/theme.jsx";
import { App } from "./App.jsx";

// Язык и тема — выше сессии и маршрутов: их читают и страница входа, и
// страница «не найдено», то есть места, где сессии ещё или уже нет.
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
