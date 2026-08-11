// Тонкий клиент над /api/admin/*. В разработке Vite проксирует /api на
// бэкенд (см. vite.config.js), поэтому здесь достаточно относительных путей.

const TOKEN_KEY = "vpn_panel_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Протухший токен должен выкидывать на форму входа из любого места, а не
// показывать пустую страницу. Слушателя ставит хранилище сессии.
const UNAUTHORIZED_EVENT = "panel:unauthorized";

export function onUnauthorized(handler) {
  window.addEventListener(UNAUTHORIZED_EVENT, handler);
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler);
}

async function request(path, { method = "GET", body, params, signal } = {}) {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, value);
      }
    }
  }

  const token = getToken();
  let response;
  try {
    response = await fetch(url.pathname + url.search, {
      method,
      signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError("Сервер недоступен", 0);
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

  if (response.status === 401) {
    setToken(null);
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    throw new ApiError("Нужно войти заново", 401);
  }

  if (!response.ok) {
    // FastAPI кладёт человеческий текст в detail — показываем его как есть,
    // это сообщения, написанные для администратора.
    const detail =
      (payload && (payload.detail || payload.message)) || `Ошибка ${response.status}`;
    throw new ApiError(typeof detail === "string" ? detail : "Ошибка запроса", response.status);
  }

  return payload;
}

export const http = {
  get: (path, params, signal) => request(path, { params, signal }),
  post: (path, body) => request(path, { method: "POST", body: body ?? {} }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  put: (path, body) => request(path, { method: "PUT", body }),
  del: (path) => request(path, { method: "DELETE" }),
};
