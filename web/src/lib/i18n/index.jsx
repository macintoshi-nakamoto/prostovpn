import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { ru } from "./ru.js";
import { en } from "./en.js";
import { isTma } from "../telegram.js";
import * as fmt from "../format.js";

const DICTS = { ru, en };
export const LANGS = ["ru", "en"];
const STORAGE_KEY = "prosto_lang";

export function readLang() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && DICTS[stored]) return stored;
  } catch {}
  // Мини-апп: аудитория русскоязычная, язык системы телефона — не
  // показатель (айфон часто на английском). По умолчанию русский,
  // переключатель RU/EN в шапке никуда не девается.
  if (isTma()) return "ru";
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
    document.documentElement.lang = lang;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {}
  }, [lang]);

  const value = useMemo(
    () => ({
      lang,
      setLang,
      toggleLang: () => setLang((prev) => (prev === "ru" ? "en" : "ru")),
      t: (key, params) => translate(lang, key, params),

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

export function useT() {
  return useI18n().t;
}

export function useFormat() {
  return useI18n().f;
}

export function capitalize(text) {
  if (!text) return text;
  return text[0].toUpperCase() + text.slice(1);
}
