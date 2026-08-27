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

// Пользователь Telegram — для витрины (аватар, имя). Доверять этим полям
// нельзя (подпись проверяет сервер при входе), показывать — можно.
export function tmaUser() {
  const wa = webApp();
  if (wa?.initDataUnsafe?.user) return wa.initDataUnsafe.user;
  try {
    const raw = tmaInitData();
    if (!raw) return null;
    const user = new URLSearchParams(raw).get("user");
    return user ? JSON.parse(user) : null;
  } catch {
    return null;
  }
}

// Параметр запуска мини-аппа (t.me/бот?startapp=КОД) — им приходят
// реферальные коды. Хеш ловим прямо при загрузке модуля: роутер срезает
// его первым же редиректом, эффекты React уже опаздывают. Значение
// переживает перезагрузку в sessionStorage.
const START_KEY = "prosto_tma_start";
try {
  const match = window.location.hash.match(/tgWebAppStartParam=([^&]+)/);
  if (match) sessionStorage.setItem(START_KEY, decodeURIComponent(match[1]));
} catch {
  // приватный режим — обойдёмся WebApp-полем
}

export function tmaStartParam() {
  const wa = webApp();
  if (wa?.initDataUnsafe?.start_param) return wa.initDataUnsafe.start_param;
  try {
    return sessionStorage.getItem(START_KEY) || "";
  } catch {
    return "";
  }
}

// Отклик как в нативном приложении. Вне Telegram — тишина.
export function tmaHaptic(kind = "light") {
  try {
    const h = webApp()?.HapticFeedback;
    if (!h) return;
    if (kind === "select") h.selectionChanged();
    else h.impactOccurred(kind);
  } catch {
    // старый клиент — без вибрации
  }
}

function rgba(hex, alpha) {
  const h = (hex || "").replace("#", "");
  if (h.length !== 6) return null;
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function mix(hexA, hexB, k) {
  const a = (hexA || "").replace("#", "");
  const b = (hexB || "").replace("#", "");
  if (a.length !== 6 || b.length !== 6) return null;
  const na = parseInt(a, 16);
  const nb = parseInt(b, 16);
  const ch = (sh) => Math.round(((na >> sh) & 255) * k + ((nb >> sh) & 255) * (1 - k));
  return `rgb(${ch(16)}, ${ch(8)}, ${ch(0)})`;
}

// Красимся в цвета КЛИЕНТА Telegram: канва — как его шапка, карточки — как
// его секции. Тогда мини-апп неотличим от родного экрана на любой платформе:
// на iOS в тёмной теме канва — почти чёрная, на Android — своя, и мы всегда
// совпадаем, потому что берём цвета из themeParams, а не угадываем.
// Канва тёмной темы приложения — константа дизайна, а не цвет клиента.
export const TMA_DARK_CANVAS = "#1a1a1c";

export function syncTmaTheme() {
  const wa = webApp();
  if (!wa) return;
  const root = document.documentElement;

  if (wa.colorScheme === "dark") {
    // Тёмная тема — наша собственная палитра (см. tma.css): переменные не
    // трогаем, а Telegram просим покрасить свою шапку и фон в нашу канву,
    // чтобы приложение сливалось с обёрткой одним цветом.
    root.style.removeProperty("--tma-canvas");
    root.style.removeProperty("--tma-card");
    root.style.removeProperty("--tma-glass");
    root.style.removeProperty("--tma-inset");
    try {
      wa.setBackgroundColor?.(TMA_DARK_CANVAS);
      wa.setHeaderColor?.(TMA_DARK_CANVAS);
    } catch {}
    return;
  }

  const p = wa.themeParams || {};
  const canvas = p.secondary_bg_color || p.bg_color;
  const card = p.section_bg_color || p.bg_color;
  if (canvas) root.style.setProperty("--tma-canvas", canvas);
  if (card) {
    root.style.setProperty("--tma-card", card);
    const glass = rgba(card, 0.66);
    if (glass) root.style.setProperty("--tma-glass", glass);
    const inset = mix(card, canvas || card, 0.55);
    if (inset) root.style.setProperty("--tma-inset", inset);
  }
  try {
    wa.setBackgroundColor?.("secondary_bg_color");
    wa.setHeaderColor?.("secondary_bg_color");
  } catch {
    // не все клиенты умеют — не страшно
  }
}

// Системная кнопка «назад»: стек обработчиков. Верхний — активный (лист
// поверх вкладки закрывается первым), пустой стек прячет кнопку.
const backStack = [];
let backBound = false;

function backDispatch() {
  const top = backStack[backStack.length - 1];
  if (top) top();
}

export function pushBack(handler) {
  const wa = webApp();
  if (!wa?.BackButton) return () => {};
  if (!backBound) {
    try {
      wa.BackButton.onClick(backDispatch);
      backBound = true;
    } catch {
      return () => {};
    }
  }
  backStack.push(handler);
  try {
    wa.BackButton.show();
  } catch {}
  return () => {
    const i = backStack.lastIndexOf(handler);
    if (i >= 0) backStack.splice(i, 1);
    try {
      if (backStack.length) wa.BackButton.show();
      else wa.BackButton.hide();
    } catch {}
  };
}

// Открыть http(s)-ссылку во внешнем браузере: там скачивание работает,
// в отличие от вебвью Telegram, где файл откроется просмотром.
export function tmaOpenLink(url) {
  try {
    const wa = webApp();
    if (wa?.openLink) {
      wa.openLink(url);
      return;
    }
  } catch {}
  try {
    window.open(url, "_blank");
  } catch {
    window.location.href = url;
  }
}

// Открыть другое приложение по его схеме (vpn:// и т.п.). Вебвью Telegram
// глушит кастомные схемы совсем, поэтому уводим во внешний браузер на
// страницу-трамплин /open.html — уже она дёргает схему из Safari/Chrome.
// Ключ кладётся во фрагмент: он не отправляется на сервер.
export function tmaOpenApp(url) {
  if (/^https?:/i.test(url)) {
    tmaOpenLink(url);
    return;
  }
  const wa = webApp();
  if (wa?.openLink) {
    try {
      wa.openLink(`${window.location.origin}/open.html#${encodeURIComponent(url)}`);
      return;
    } catch {}
  }
  try {
    window.location.href = url;
  } catch {}
}

let tapsBound = false;

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

  syncTmaTheme();
  try {
    wa.onEvent?.("themeChanged", syncTmaTheme);
  } catch {}

  // Лёгкая вибрация на каждый тап по кнопке или ссылке — как в системных
  // приложениях. Один раз на документ, дальше живёт само.
  if (!tapsBound) {
    tapsBound = true;
    document.addEventListener(
      "click",
      (event) => {
        if (event.target?.closest?.("button, a")) tmaHaptic("light");
      },
      { capture: true, passive: true },
    );
  }
}
