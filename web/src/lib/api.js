// Тонкий клиент над /api/v1/*. В разработке Vite проксирует /api на бэкенд
// (см. vite.config.js), поэтому здесь достаточно относительных путей.

const TOKEN_KEY = "prosto_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
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
      body: { login, password, platform: "web" },
    }),

  register: (login, password, email) =>
    request("/api/v1/register", {
      method: "POST",
      body: { login, password, email: email || null, platform: "web" },
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
