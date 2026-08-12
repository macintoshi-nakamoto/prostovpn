// Тонкий клиент над /api/v1/*. В разработке Vite проксирует /api на бэкенд
// (см. vite.config.js), поэтому здесь достаточно относительных путей.

const TOKEN_KEY = "prosto_token";
const DEVICE_KEY = "prosto_browser_id";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Постоянный идентификатор этого браузера.
 *
 * Не для лимита устройств — браузер в нём не участвует, — а чтобы повторный
 * вход в кабинет заменял прежнюю сессию, а не добавлял к ней ещё одну.
 * Иначе у человека, заходящего в кабинет раз в неделю, копится список
 * живых токенов, каждый из которых — действующий доступ к его учётке.
 */
function browserId() {
  let value = localStorage.getItem(DEVICE_KEY);
  if (!value) {
    value =
      // randomUUID есть не везде (http-контекст, старые вебвью) — тогда
      // хватит случайной строки: это идентификатор, а не секрет.
      crypto.randomUUID?.() ?? `web-${Math.random().toString(36).slice(2)}${Date.now()}`;
    localStorage.setItem(DEVICE_KEY, value);
  }
  return value;
}

/** Как назвать этот браузер в журнале входов. */
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

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    // Код причины из заголовка X-Error-Code: по нему выбираем свой текст,
    // а не показываем сырое сообщение бэкенда.
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

  renew: (planCode) =>
    request("/api/v1/account/renew", {
      method: "POST",
      auth: true,
      body: { plan_code: planCode || null },
    }),

  logout: () => request("/api/v1/logout", { method: "POST", auth: true }).catch(() => {}),

  plans: () => request("/api/v1/plans"),

  downloads: () => request("/api/v1/downloads"),
};
