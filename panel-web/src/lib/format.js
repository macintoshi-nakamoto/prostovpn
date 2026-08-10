// Форматирование чисел, денег, объёмов и дат. Одно место на всю панель —
// иначе «199 ₽» и «199.00 RUB» встречаются на соседних экранах.

const GB = 1024 ** 3;

const moneyFmt = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});
const moneyFmtPrecise = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const numFmt = new Intl.NumberFormat("ru-RU");

const CURRENCY_SIGN = { RUB: "₽", USD: "$", EUR: "€", USDT: "USDT" };

export function currencySign(code) {
  return CURRENCY_SIGN[code] || code || "";
}

export function money(value, currency = "RUB", { precise = false } = {}) {
  const number = Number(value ?? 0);
  if (!isFinite(number)) return "—";
  const fmt = precise || (number % 1 !== 0 && Math.abs(number) < 1000) ? moneyFmtPrecise : moneyFmt;
  return `${fmt.format(number)} ${currencySign(currency)}`.trim();
}

export function moneyShort(value, currency = "RUB") {
  const number = Number(value ?? 0);
  if (!isFinite(number)) return "—";
  const sign = currencySign(currency);
  if (Math.abs(number) >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}М ${sign}`;
  if (Math.abs(number) >= 10_000) return `${Math.round(number / 1000)}к ${sign}`;
  return `${moneyFmt.format(number)} ${sign}`;
}

export function num(value) {
  return numFmt.format(Number(value ?? 0));
}

/** Объём трафика. Гигабайты — рабочая единица панели, поэтому не мельчим. */
export function bytes(value) {
  const b = Number(value ?? 0);
  if (!isFinite(b) || b <= 0) return "0 ГБ";
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(0)} КБ`;
  if (b < GB) return `${(b / 1024 ** 2).toFixed(0)} МБ`;
  if (b < 100 * GB) return `${(b / GB).toFixed(1)} ГБ`;
  if (b < 1024 * GB) return `${(b / GB).toFixed(0)} ГБ`;
  return `${(b / 1024 ** 4).toFixed(2)} ТБ`;
}

export function gb(value) {
  return Number(value ?? 0) / GB;
}

export function toBytes(gigabytes) {
  return Math.round(Number(gigabytes || 0) * GB);
}

/** Лимит трафика: отсутствие лимита и есть безлимит. */
export function trafficLimit(limitBytes) {
  return limitBytes == null ? "Безлимит" : bytes(limitBytes);
}

export function percent(value, digits = 0) {
  const n = Number(value ?? 0);
  return `${n.toFixed(digits)}%`;
}

const dateFmt = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
const dateShortFmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
const timeFmt = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });

function parse(value) {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

export function date(value) {
  const d = parse(value);
  return d ? dateFmt.format(d) : "—";
}

export function dateShort(value) {
  const d = parse(value);
  return d ? dateShortFmt.format(d) : "—";
}

export function dateTime(value) {
  const d = parse(value);
  return d ? `${dateFmt.format(d)}, ${timeFmt.format(d)}` : "—";
}

/** «5 минут назад» — для сессий и рукопожатий это читается быстрее даты. */
export function ago(value) {
  const d = parse(value);
  if (!d) return "—";
  const seconds = Math.round((Date.now() - d.getTime()) / 1000);
  if (seconds < 60) return "только что";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} ${plural(minutes, "минуту", "минуты", "минут")} назад`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ${plural(hours, "час", "часа", "часов")} назад`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} ${plural(days, "день", "дня", "дней")} назад`;
  return date(d);
}

export function plural(count, one, few, many) {
  const n = Math.abs(count) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return many;
  if (n1 > 1 && n1 < 5) return few;
  if (n1 === 1) return one;
  return many;
}

export function days(count) {
  if (count == null) return "—";
  return `${count} ${plural(count, "день", "дня", "дней")}`;
}

export function initials(name, login) {
  const source = (name || login || "?").trim();
  const parts = source.split(/[\s-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

/** Флаг страны эмодзи из двухбуквенного кода — легче любой иконки. */
export function flag(countryCode) {
  if (!countryCode || countryCode.length !== 2) return "🌐";
  const base = 127397;
  return String.fromCodePoint(...[...countryCode.toUpperCase()].map((c) => c.charCodeAt(0) + base));
}
