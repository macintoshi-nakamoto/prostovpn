const API = "/api/v1";
const TOKEN_KEY = "prosto.token";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(value) {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {}
}

async function request(method, path, body) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(API + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.", 0);
  }

  if (response.status === 204) return null;

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    if (response.status === 401) setToken(null);
    throw new ApiError(detailOf(data) || fallbackMessage(response.status), response.status);
  }
  return data;
}

function detailOf(data) {
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) return detail[0]?.msg || null;
  return null;
}

function fallbackMessage(status) {
  if (status === 429) return "Слишком много попыток. Подождите немного.";
  if (status === 404) return "Не найдено.";
  if (status >= 500) return "Сервис временно недоступен. Попробуйте через минуту.";
  return "Что-то пошло не так.";
}

export const api = {
  plans: () => request("GET", "/plans"),
  downloads: () => request("GET", "/downloads"),

  createOrder: (payload) => request("POST", "/orders", payload),
  orderStatus: (id) => request("GET", `/orders/${encodeURIComponent(id)}/status`),
  mockPay: (id) => request("POST", "/billing/mock/pay", { order_id: id }),

  login: (payload) => request("POST", "/login", payload),
  account: () => request("GET", "/account"),
  changePassword: (payload) => request("POST", "/account/password", payload),
  unlinkDevice: (id) => request("DELETE", `/account/devices/${id}`),
  renew: (planCode) => request("POST", "/account/renew", { plan_code: planCode || null }),
};

const RUB = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const SIGNS = { RUB: "₽", USD: "$", EUR: "€" };

export function money(kopecks, currency = "RUB") {
  const value = Number(kopecks || 0) / 100;
  const sign = SIGNS[currency] || currency;
  const digits = Number.isInteger(value) ? 0 : 2;
  return `${value.toLocaleString("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} ${sign}`;
}

export function moneyParts(kopecks, currency = "RUB") {
  const value = Number(kopecks || 0) / 100;
  return { value: RUB.format(Math.round(value)), sign: SIGNS[currency] || currency };
}

export function plural(count, one, few, many) {
  const n = Math.abs(count) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return many;
  if (n1 > 1 && n1 < 5) return few;
  if (n1 === 1) return one;
  return many;
}

export function term(days) {
  if (days % 365 === 0) {
    const years = days / 365;
    return `${years} ${plural(years, "год", "года", "лет")}`;
  }
  if (days % 30 === 0) {
    const months = days / 30;
    return `${months} ${plural(months, "месяц", "месяца", "месяцев")}`;
  }
  return `${days} ${plural(days, "день", "дня", "дней")}`;
}

export function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch],
  );
}
