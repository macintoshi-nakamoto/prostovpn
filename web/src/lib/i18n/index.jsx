import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { ru } from "./ru.js";
import { en } from "./en.js";
import * as fmt from "../format.js";

/*
 * Свой маленький i18n вместо библиотеки.
 *
 * Языка ровно два, строк — несколько сотен, и всё, что нужно от движка, это
 * подстановки и множественное число. i18next с плагинами весит больше, чем
 * оба словаря вместе, и тянет за собой отдельный формат ключей; здесь ключ —
 * это путь в обычном объекте, который видно в редакторе целиком.
 *
 * Выбор языка живёт в localStorage, а не в адресе. Отдельные /en/... потребовали
 * бы второго дерева маршрутов и правки nginx (try_files сейчас один), а ссылки,
 * которыми люди уже делятся, разъехались бы на два набора.
 */

const DICTS = { ru, en };
export const LANGS = ["ru", "en"];
const STORAGE_KEY = "prosto_lang";

/** Язык первого захода: сохранённый → системный → русский. */
export function readLang() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && DICTS[stored]) return stored;
  } catch {
    // Приватный режим в Safari запрещает localStorage целиком — не повод
    // ронять приложение на первой же строке.
  }
  const nav = typeof navigator !== "undefined" ? navigator.languages || [navigator.language] : [];
  for (const tag of nav) {
    const code = String(tag || "").slice(0, 2).toLowerCase();
    if (DICTS[code]) return code;
  }
  return "ru";
}

function resolve(dict, key) {
  return String(key)
    .split(".")
    .reduce((node, part) => (node == null ? node : node[part]), dict);
}

/**
 * Форма множественного числа.
 *
 * Английских форм две, русских три, и правило для русского то же, что в
 * format.js: 1 — «день», 2–4 — «дня», остальное и подростковые числа — «дней».
 */
function pickPlural(lang, count, forms) {
  if (lang === "en") return Math.abs(count) === 1 ? forms.one : forms.other;
  const n = Math.abs(count) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return forms.many;
  if (n1 > 1 && n1 < 5) return forms.few;
  if (n1 === 1) return forms.one;
  return forms.many;
}

function interpolate(text, params) {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name) =>
    params[name] == null ? whole : String(params[name]),
  );
}

function translate(lang, key, params) {
  // Русский — исходный язык словаря, поэтому он же и запасной: пропущенный
  // английский ключ покажет русскую строку, а не голый `landing.hero.lead`.
  let node = resolve(DICTS[lang] || ru, key);
  if (node == null) node = resolve(ru, key);
  if (node == null) {
    if (import.meta.env.DEV) console.warn(`[i18n] нет строки: ${key}`);
    return key;
  }
  if (node && typeof node === "object" && !Array.isArray(node) && "one" in node) {
    node = pickPlural(lang, params?.count ?? 0, node);
  }
  if (typeof node !== "string") return node;
  return interpolate(node, params);
}

/** Готовые форматтеры текущего языка — см. комментарий в format.js. */
function formatters(lang) {
  return {
    money: (value, currency) => fmt.money(value, currency, lang),
    moneyFromKopecks: (value, currency) => fmt.moneyFromKopecks(value, currency, lang),
    bytes: (value) => fmt.bytes(value, lang),
    longDate: (value) => fmt.longDate(value, lang),
    shortDate: (value) => fmt.shortDate(value, lang),
    days: (value) => fmt.days(value, lang),
    ago: (value) => fmt.ago(value, lang),
  };
}

const Ctx = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(readLang);

  useEffect(() => {
    // lang у <html> — не украшение: от него зависят переносы, кавычки и то,
    // каким голосом читает страницу скринридер.
    document.documentElement.lang = lang;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      // См. readLang: без хранилища язык просто не переживёт перезагрузку.
    }
  }, [lang]);

  const value = useMemo(
    () => ({
      lang,
      setLang,
      toggleLang: () => setLang((prev) => (prev === "ru" ? "en" : "ru")),
      t: (key, params) => translate(lang, key, params),
      // raw отдаёт узел словаря как есть — для массивов карточек и блоков,
      // которые компонент перебирает сам.
      raw: (key) => resolve(DICTS[lang] || ru, key) ?? resolve(ru, key) ?? [],
      f: formatters(lang),
    }),
    [lang],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n вне I18nProvider");
  return ctx;
}

/** Короткий доступ к t() — им пользуется большинство компонентов. */
export function useT() {
  return useI18n().t;
}

/** Форматтеры, привязанные к текущему языку. */
export function useFormat() {
  return useI18n().f;
}

/** Первая буква прописной: для подписей, которые в словаре начинаются строчной. */
export function capitalize(text) {
  if (!text) return text;
  return text[0].toUpperCase() + text.slice(1);
}
