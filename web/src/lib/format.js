// Форматирование для сайта: деньги, даты, трафик, дни.

export function money(rubles, currency = "RUB") {
  if (rubles == null) return "";
  const sign = currency === "RUB" ? " ₽" : ` ${currency}`;
  // Разряды неразрывным пробелом, как в макете: «2 028 ₽».
  const rounded = Math.round(Number(rubles));
  return rounded.toLocaleString("ru-RU").replace(/,/g, " ") + sign;
}

export function moneyFromKopecks(kopecks, currency = "RUB") {
  if (kopecks == null) return "";
  return money(kopecks / 100, currency);
}

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export function longDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}`;
}

export function bytes(value) {
  if (!value) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
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

export function plural(count, forms = DAY_FORMS) {
  const n = Math.abs(count) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return forms[2];
  if (n1 > 1 && n1 < 5) return forms[1];
  if (n1 === 1) return forms[0];
  return forms[2];
}

export function days(count) {
  return `${count} ${plural(count)}`;
}

/** «активно сейчас», «был вчера», «был 3 дня назад» — для устройств. */
export function ago(iso) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 3) return "активно сейчас";
  if (min < 60) return `был ${min} мин назад`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `был ${hours} ${plural(hours, ["час", "часа", "часов"])} назад`;
  const d = Math.floor(hours / 24);
  if (d === 1) return "был вчера";
  return `был ${d} ${plural(d)} назад`;
}
