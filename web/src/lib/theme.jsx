import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { isTma, tmaColorScheme } from "./telegram.js";

const STORAGE_KEY = "prosto_theme";
const Ctx = createContext(null);

export function readTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {}
  // Внутри Telegram, пока тему не выбрали руками, живём в теме Telegram —
  // белый кабинет в тёмном клиенте выглядит как вспышка.
  if (isTma()) return tmaColorScheme();
  return "light";
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(readTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);

    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#12141a" : "#FA4C16");
  }, [theme]);

  const value = useMemo(() => {
    const choose = (next) => {
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {}
      setTheme(next);
    };
    return {
      theme,
      dark: theme === "dark",
      setTheme: choose,
      toggle: () => choose(theme === "dark" ? "light" : "dark"),
    };
  }, [theme]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme вне ThemeProvider");
  return ctx;
}
