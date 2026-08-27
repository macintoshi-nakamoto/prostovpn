// Режим мини-приложения Telegram.
//
// Telegram открывает сайт со скриптом telegram-web-app.js (подключён в
// index.html) и кладёт подписанные данные в window.Telegram.WebApp.initData —
// они же приходят в хеше адреса (#tgWebAppData=...). Хеш проверяем тоже:
// он появляется раньше, чем успевает исполниться внешний скрипт, и остаётся
// единственным признаком, если скрипт не загрузился.
//
// Признак «мы внутри Telegram» запоминается на сессию вкладки: SPA меняет
// адрес при навигации, и хеш с tgWebAppData исчезает после первого же
// перехода.

const KEY = "prosto_tma";

function webApp() {
  return typeof window !== "undefined" ? window.Telegram?.WebApp : undefined;
}

function markedInHash() {
  try {
    return window.location.hash.includes("tgWebAppData=");
  } catch {
    return false;
  }
}

export function isTma() {
  try {
    if (sessionStorage.getItem(KEY) === "1") return true;
  } catch {
    // приватный режим — обходимся без памяти
  }
  const inside = Boolean(webApp()?.initData) || markedInHash();
  if (inside) {
    try {
      sessionStorage.setItem(KEY, "1");
    } catch {
      // ну и ладно
    }
  }
  return inside;
}

export function tmaInitData() {
  const wa = webApp();
  if (wa?.initData) return wa.initData;
  try {
    const match = window.location.hash.match(/tgWebAppData=([^&]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  } catch {
    return "";
  }
}

// Тема Telegram: тёмная/светлая — чтобы кабинет не спорил с обёрткой.
export function tmaColorScheme() {
  return webApp()?.colorScheme === "dark" ? "dark" : "light";
}

export function initTma() {
  const wa = webApp();
  if (!wa) return;
  try {
    wa.ready();
    wa.expand();
    // Свайп вниз закрывает приложение посреди прокрутки кабинета — выключаем.
    wa.disableVerticalSwipes?.();
  } catch {
    // Старый клиент без части методов — не повод падать.
  }
}
