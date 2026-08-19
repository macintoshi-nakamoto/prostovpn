// Форматирование для сайта: деньги, даты, трафик, дни.
//
// Каждая функция принимает язык последним параметром со значением "ru" по
// умолчанию — так старые вызовы из кода, где языка нет, продолжают работать.
// Компоненты берут не эти функции напрямую, а привязанные к текущему языку
// версии через useFormat(): иначе смена языка перерисовала бы подписи, а
// «12 августа 2026» под английским заголовком осталось бы прежним.

const RU_MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

const EN_MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/**
 * Время с бэкенда — всегда UTC, но без пометки зоны.
 *
 * `new Date("2026-08-19T13:20:00")` считает такую строку МЕСТНЫМ временем, и
 * у человека в Москве только что подключившееся устройство показывалось как
 * «был 3 часа назад». Дописываем Z, если зоны нет, — дальше обычные
 * get-методы сами переводят в местное время читателя.
 */
function parseUtc(iso) {
  if (iso instanceof Date) return iso;
  const hasZone = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`);
}

export function money(rubles, currency = "RUB", lang = "ru") {
  if (rubles == null) return "";
  const sign = currency === "RUB" ? " ₽" : ` ${currency}`;
  const rounded = Math.round(Number(rubles));
  const grouped = rounded.toLocaleString(lang === "en" ? "en-US" : "ru-RU");
  // В русском макете разряды разделяет пробел: «2 028 ₽». Если локали ru-RU в
  // системе нет, toLocaleString вернёт группировку через запятую — заменяем,
  // иначе одно число на странице будет отличаться от остальных.
  return (lang === "en" ? grouped : grouped.replace(/,/g, " ")) + sign;
}

export function moneyFromKopecks(kopecks, currency = "RUB", lang = "ru") {
  if (kopecks == null) return "";
  return money(kopecks / 100, currency, lang);
}

export function longDate(iso, lang = "ru") {
  if (!iso) return "";
  const d = parseUtc(iso);
  if (lang === "en") return `${EN_MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
  return `${d.getDate()} ${RU_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function shortDate(iso, lang = "ru") {
  if (!iso) return "";
  const d = parseUtc(iso);
  const p = (n) => String(n).padStart(2, "0");
  // Порядок частей разный не для красоты: 05.08 и 08/05 в одном виде читались
  // бы как разные даты, и человек ошибётся в дне окончания подписки.
  if (lang === "en") return `${p(d.getMonth() + 1)}/${p(d.getDate())}/${d.getFullYear()}`;
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}`;
}

const BYTE_UNITS = {
  ru: ["Б", "КБ", "МБ", "ГБ", "ТБ"],
  en: ["B", "KB", "MB", "GB", "TB"],
};

export function bytes(value, lang = "ru") {
  const units = BYTE_UNITS[lang] || BYTE_UNITS.ru;
  if (!value) return `0 ${units[0]}`;
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  const rounded = n >= 100 || i === 0 ? Math.round(n) : Math.round(n * 10) / 10;
  return `${rounded} ${units[i]}`;
}

const DAY_FORMS = ["день", "дня", "дней"];

/** Русские три формы. Английские две живут в словаре, здесь они не нужны. */
export function plural(count, forms = DAY_FORMS) {
  const n = Math.abs(count) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return forms[2];
  if (n1 > 1 && n1 < 5) return forms[1];
  if (n1 === 1) return forms[0];
  return forms[2];
}

export function days(count, lang = "ru") {
  if (lang === "en") return `${count} ${Math.abs(count) === 1 ? "day" : "days"}`;
  return `${count} ${plural(count)}`;
}

/** «активно сейчас», «был вчера», «был 3 дня назад» — для устройств. */
export function ago(iso, lang = "ru") {
  if (!iso) return "";
  const en = lang === "en";
  const diff = Date.now() - parseUtc(iso).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 3) return en ? "active now" : "активно сейчас";
  if (min < 60) return en ? `${min} min ago` : `был ${min} мин назад`;
  const hours = Math.floor(min / 60);
  if (hours < 24) {
    return en
      ? `${hours} ${hours === 1 ? "hour" : "hours"} ago`
      : `был ${hours} ${plural(hours, ["час", "часа", "часов"])} назад`;
  }
  const d = Math.floor(hours / 24);
  if (d === 1) return en ? "yesterday" : "был вчера";
  return en ? `${d} days ago` : `был ${d} ${plural(d)} назад`;
}
