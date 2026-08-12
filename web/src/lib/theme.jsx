import { createContext, useContext, useEffect, useMemo, useState } from "react";

/*
 * Тёмная тема сайта.
 *
 * Выбор темы стоит атрибутом data-theme на <html>, а не классом на корне
 * приложения: тот же атрибут ставит крошечный скрипт в index.html — до того,
 * как React вообще загрузится. Иначе первым кадром человеку с тёмной темой
 * бьёт в глаза белый фон, и только потом страница темнеет.
 *
 * Ключ хранилища отличается от панельного (vpn_panel_theme) намеренно: сайт и
 * админка живут на одном домене, и общий ключ связал бы их темы в одну.
 */

const STORAGE_KEY = "prosto_theme";
const Ctx = createContext(null);

/** Тема первого захода: сохранённая → системная → светлая. */
export function readTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Приватный режим может запрещать хранилище — тогда просто системная.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Выбирал ли человек тему руками. Пока нет — идём за системой. */
function chosen() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark";
  } catch {
    return false;
  }
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

  useEffect(() => {
    // Пока человек не выбрал тему сам, следуем за системой на лету: переключение
    // на уровне ОС не должно требовать перезагрузки вкладки.
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media) return undefined;
    const onChange = (e) => {
      if (!chosen()) setTheme(e.matches ? "dark" : "light");
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const value = useMemo(() => {
    // Пишем в хранилище здесь, а не в эффекте: эффект сохранял бы и тему,
    // доставшуюся от системы, и слушатель выше замолчал бы навсегда, хотя
    // человек ничего не выбирал.
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
