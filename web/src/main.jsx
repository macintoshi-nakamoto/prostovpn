import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

// Базовые стили — первым импортом, до компонентов: в сборку css попадает в
// порядке импортов, и при равной специфичности побеждает тот, что ниже.
// Компонент должен уточнять базу, а не наоборот.
import "./styles/base.css";

import { SessionProvider } from "./lib/session.jsx";
import { App } from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
);
