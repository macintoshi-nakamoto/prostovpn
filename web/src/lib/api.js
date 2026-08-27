import { takeRef } from "./referral.js";

const TOKEN_KEY = "prosto_token";
const DEVICE_KEY = "prosto_browser_id";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
}

function browserId() {
  let value = localStorage.getItem(DEVICE_KEY);
  if (!value) {
    value =

      crypto.randomUUID?.() ?? `web-${Math.random().toString(36).slice(2)}${Date.now()}`;
    localStorage.setItem(DEVICE_KEY, value);
  }
  return value;
}

function browserName() {
  const ua = navigator.userAgent || "";
  const name =
    [
      ["Edg/", "Edge"],
      ["OPR/", "Opera"],
      ["YaBrowser", "Yandex"],
      ["Firefox", "Firefox"],
      ["Chrome", "Chrome"],
      ["Safari", "Safari"],
    ].find(([mark]) => ua.includes(mark))?.[1] || "Браузер";
  return name;
}

export function setToken(token, { remember = true } = {}) {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);

  if (!token) return;

  (remember ? localStorage : sessionStorage).setItem(TOKEN_KEY, token);
}

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = "ApiError";
    this.status = status;

    this.code = code || "";
  }
}

async function request(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Не удалось связаться с сервером. Проверьте интернет", 0);
  }

  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (response.status === 401 && auth) {
    setToken(null);
  }

  if (!response.ok) {
    const detail =
      (payload && (payload.detail || payload.message)) || `Ошибка ${response.status}`;
    throw new ApiError(
      typeof detail === "string" ? detail : "Ошибка запроса",
      response.status,
      response.headers.get("X-Error-Code"),
    );
  }

  return payload;
}

export const api = {
  login: (login, password) =>
    request("/api/v1/login", {
      method: "POST",
      body: {
        login,
        password,
        platform: "web",
        device_id: browserId(),
        device_name: browserName(),
      },
    }),

  register: (login, password, email) =>
    request("/api/v1/register", {
      method: "POST",
      body: {
        login,
        password,
        email: email || null,
        platform: "web",
        device_id: browserId(),
        device_name: browserName(),
        ref: takeRef(),
      },
    }),

  account: () => request("/api/v1/account", { auth: true }),

  changePassword: (currentPassword, newPassword) =>
    request("/api/v1/account/password", {
      method: "POST",
      auth: true,
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  unlinkDevice: (deviceId) =>
    request(`/api/v1/account/devices/${deviceId}`, { method: "DELETE", auth: true }),

  setEmail: (email) =>
    request("/api/v1/account/email", { method: "POST", auth: true, body: { email } }),

  referrals: () => request("/api/v1/account/referrals", { auth: true }),

  enableIos: (serverId) =>
    request("/api/v1/account/ios", {
      method: "POST",
      auth: true,
      body: { server_id: serverId ?? null },
    }),

  addIosKey: (serverId) =>
    request("/api/v1/account/ios/keys", {
      method: "POST",
      auth: true,
      body: { server_id: serverId ?? null },
    }),

  deleteIosKey: (slot) =>
    request(`/api/v1/account/ios/keys/${slot}`, { method: "DELETE", auth: true }),

  disconnectIosKey: (slot) =>
    request(`/api/v1/account/ios/keys/${slot}/disconnect`, { method: "POST", auth: true }),

  enableIosKey: (slot) =>
    request(`/api/v1/account/ios/keys/${slot}/enable`, { method: "POST", auth: true }),

  renew: (planCode, quantity = 1, paymentMethod = null) =>
    request("/api/v1/account/renew", {
      method: "POST",
      auth: true,
      body: { plan_code: planCode || null, quantity, payment_method: paymentMethod },
    }),

  transfers: () => request("/api/v1/account/transfers", { auth: true }),

  transferDays: (recipient, days, note) =>
    request("/api/v1/account/transfers", {
      method: "POST",
      auth: true,
      body: { recipient, days, note: note || null },
    }),

  forgotPassword: (email) =>
    request("/api/v1/password/forgot", { method: "POST", body: { email } }),

  checkResetToken: (token) =>
    request(`/api/v1/password/reset/${encodeURIComponent(token)}`),

  resetPassword: (token, password) =>
    request("/api/v1/password/reset", { method: "POST", body: { token, password } }),

  orderStatus: (orderId) => request(`/api/v1/orders/${encodeURIComponent(orderId)}/status`),

  recurring: () => request("/api/v1/account/recurring", { auth: true }),

  recurringCreate: (planCode) =>
    request("/api/v1/account/recurring", {
      method: "POST",
      auth: true,
      body: { plan_code: planCode },
    }),

  recurringCancel: () =>
    request("/api/v1/account/recurring/cancel", { method: "POST", auth: true }),

  freeze: () => request("/api/v1/account/freeze", { method: "POST", auth: true }),

  unfreeze: () => request("/api/v1/account/unfreeze", { method: "POST", auth: true }),

  logout: () => request("/api/v1/logout", { method: "POST", auth: true }).catch(() => {}),

  plans: () => request("/api/v1/plans"),

  downloads: () => request("/api/v1/downloads"),
};
