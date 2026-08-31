import { createContext, useContext, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "prosto_theme";
const Ctx = createContext(null);

export function readTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {}
  // Пока тему не выбрали руками — тёмная: и на сайте, и в мини-аппе.
  return "dark";
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(readTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);

    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#1a1a1c" : "#FA4C16");
  }, [theme]);

  const value = useMemo(() => {
    const choose = (next) => {
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {}
      // На время смены включаем переходы цвета на всём дереве: тема
      // перетекает, а не щёлкает. Класс живёт меньше полсекунды, чтобы
      // не тормозить обычные взаимодействия постоянными transition.
      const root = document.documentElement;
      root.classList.add("theme-anim");
      window.setTimeout(() => root.classList.remove("theme-anim"), 450);
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
