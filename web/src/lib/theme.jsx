import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { BRAND } from "./brand.js";

/**
 * Тема: тёмная в кабинете и в мини-приложении, светлая на витрине.
 *
 * Значения по умолчанию разные, потому что это разные вещи. Кабинет —
 * приложение: в нём сидят подолгу и часто ночью. Лендинг — витрина: её
 * читают один раз, при свете дня, и белый лист там привычнее.
 *
 * Отсюда и два ключа в хранилище вместо одного общего. С общим стоило
 * тронуть переключатель в любой половине — и обе становились одного цвета,
 * то есть расстановка, ради которой всё затевалось, ломалась от первого же
 * нажатия. Теперь выбор человека живёт отдельно для витрины и отдельно для
 * кабинета, и каждый переключатель меняет ровно то, что перед глазами.
 *
 * Первый кадр рисует скрипт в index.html по этим же правилам, слово в
 * слово. Здесь мы лишь подхватываем то, что он уже поставил на <html>:
 * разойдись два расчёта — первый кадр спорил бы со вторым и мигал.
 */

const KEY = { app: "prosto_theme_app", site: "prosto_theme_site" };

function defaultTheme(app) {
  return app ? "dark" : "light";
}

function stored(app) {
  try {
    const saved = localStorage.getItem(app ? KEY.app : KEY.site);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // приватный режим — обходимся значением по умолчанию
  }
  return null;
}

/**
 * Тема, которая сейчас на экране.
 *
 * Спрашиваем сам документ, а не хранилище: атрибут ставит скрипт в
 * index.html ещё до React, и это единственное значение, с которым первый
 * кадр заведомо совпадает.
 */
export function readTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

const Ctx = createContext(null);

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(readTheme);
  // В какой половине сайта мы сейчас — от этого зависит, в какой ключ
  // писать выбор. Значение до первого перехода берём с корня документа:
  // класс app туда поставил тот же скрипт в index.html. У бренда без
  // витрины (Rus VPN) половина всегда одна — кабинет.
  const app = useRef(!BRAND.landing || document.documentElement.classList.contains("app"));

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);

    // Цвет строки состояния браузера — из токенов бренда, а не цифрами:
    // тёмная тема — канва, светлая — акцент (шапка сайта).
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      const styles = getComputedStyle(document.documentElement);
      const color = styles.getPropertyValue(theme === "dark" ? "--bg" : "--accent").trim();
      meta.setAttribute("content", color || (theme === "dark" ? "#1a1a1c" : "#FA4C16"));
    }
  }, [theme]);

  // Переход между витриной и кабинетом. Тему, выбранную здесь руками, не
  // трогаем; не выбирали — берём ту, что для этой половины по умолчанию.
  // Плавное перетекание не включаем: страница и так меняется целиком, и
  // тянуть за ней ещё и цвет полсекунды — только мазать.
  const follow = useCallback((isApp) => {
    app.current = isApp;
    setTheme(stored(isApp) || defaultTheme(isApp));
  }, []);

  const value = useMemo(() => {
    const choose = (next) => {
      try {
        localStorage.setItem(app.current ? KEY.app : KEY.site, next);
      } catch {
        // не сохранилось — на этой вкладке тема всё равно сменится
      }
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
      follow,
    };
  }, [theme, follow]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme вне ThemeProvider");
  return ctx;
}
