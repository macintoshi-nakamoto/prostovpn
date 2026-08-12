import { createContext, useContext, useEffect, useMemo, useState } from "react";

/*
 * Тёмная тема сайта.
 *
 * Выбор темы стоит атрибутом data-theme на <html>, а не классом на корне
 * приложения: тот же атрибут ставит крошечный скрипт в index.html — до того,
 * как React вообще загрузится. Иначе первым кадром человеку с тёмной темой
 * бьёт в глаза белый фон, и только потом страница темнеет.
 *
 * По умолчанию сайт светлый, и системную настройку мы не читаем: макет
 * рисован светлым, это лицо продукта — тёмную включают рукой, и выбор
 * запоминается. (Так решено владельцем; раньше первый заход шёл за системой.)
 *
 * Ключ хранилища отличается от панельного (vpn_panel_theme) намеренно: сайт и
 * админка живут на одном домене, и общий ключ связал бы их темы в одну.
 */

const STORAGE_KEY = "prosto_theme";
const Ctx = createContext(null);

/** Тема первого захода: сохранённая, иначе светлая. */
export function readTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Приватный режим может запрещать хранилище — тогда просто светлая.
  }
  return "light";
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(readTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    // Цвет строки состояния в мобильных браузерах: без этого над тёмной
    // страницей остаётся оранжевая полоса из статического meta в index.html.
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#12141a" : "#FA4C16");
  }, [theme]);

  const value = useMemo(() => {
    const choose = (next) => {
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Без хранилища выбор живёт до перезагрузки.
      }
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
