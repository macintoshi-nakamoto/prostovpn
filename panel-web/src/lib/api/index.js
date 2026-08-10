// Единая точка входа в API: страницы импортируют `api`, а не отдельные файлы.

import { http, setToken } from "./client";

const BASE = "/api/admin";

export const authApi = {
  login: async (login, password) => {
    const data = await http.post(`${BASE}/login`, { login, password });
    setToken(data.token);
    return data;
  },
  logout: () => http.post(`${BASE}/logout`).finally(() => setToken(null)),
  me: () => http.get(`${BASE}/me`),
};

export const usersApi = {
  list: (params, signal) => http.get(`${BASE}/users`, params, signal),
  get: (id) => http.get(`${BASE}/users/${id}`),
  create: (payload) => http.post(`${BASE}/users`, payload),
  update: (id, payload) => http.patch(`${BASE}/users/${id}`, payload),
  remove: (id) => http.del(`${BASE}/users/${id}`),

  enable: (id) => http.post(`${BASE}/users/${id}/enable`),
  disable: (id) => http.post(`${BASE}/users/${id}/disable`),
  block: (id, reason) => http.post(`${BASE}/users/${id}/block`, { reason }),
  unblock: (id) => http.post(`${BASE}/users/${id}/unblock`),

  setTrafficLimit: (id, payload) => http.post(`${BASE}/users/${id}/traffic-limit`, payload),
  resetTraffic: (id) => http.post(`${BASE}/users/${id}/traffic-reset`),
  extend: (id, payload) => http.post(`${BASE}/users/${id}/extend`, payload),
  resetPassword: (id) => http.post(`${BASE}/users/${id}/password`),
  // Показ пароля — POST, а не GET: GET оседает в истории браузера и логах
  // прокси, а каждый такой запрос пишется в журнал поимённо.
  revealPassword: (id) => http.post(`${BASE}/users/${id}/reveal`),
  killSession: (userId, sessionId) => http.del(`${BASE}/users/${userId}/sessions/${sessionId}`),
};

export const ordersApi = {
  list: (params, signal) => http.get(`${BASE}/orders`, params, signal),
  get: (id) => http.get(`${BASE}/orders/${id}`),
  // Выдать доступ руками, когда вебхук не дошёл, а деньги получены.
  fulfil: (id) => http.post(`${BASE}/orders/${id}/fulfil`),
  refund: (id, reason) => http.post(`${BASE}/orders/${id}/refund`, { reason }),

  deliveries: (params) => http.get(`${BASE}/deliveries`, params),
  retryDelivery: (id) => http.post(`${BASE}/deliveries/${id}/retry`),
  events: (params) => http.get(`${BASE}/billing-events`, params),
};

export const auditApi = {
  list: (params, signal) => http.get(`${BASE}/audit`, params, signal),
  actions: () => http.get(`${BASE}/audit/actions`),
};

export const serversApi = {
  list: () => http.get(`${BASE}/servers`),
  create: (payload) => http.post(`${BASE}/servers`, payload),
  update: (id, payload) => http.put(`${BASE}/servers/${id}`, payload),
  toggle: (id) => http.post(`${BASE}/servers/${id}/toggle`),
  remove: (id) => http.del(`${BASE}/servers/${id}`),
  syncTraffic: (id) => http.post(`${BASE}/servers/${id}/sync-traffic`),
};

export const keysApi = {
  list: (params, signal) => http.get(`${BASE}/keys`, params, signal),
  revoke: (id) => http.post(`${BASE}/keys/${id}/revoke`),
  reissue: (userId, serverId) => http.post(`${BASE}/keys/reissue/${userId}/${serverId}`),
  syncAll: () => http.post(`${BASE}/keys/sync-traffic`),
};

export const releasesApi = {
  list: () => http.get(`${BASE}/releases`),
  platforms: () => http.get(`${BASE}/releases/platforms`),
  create: (payload) => http.post(`${BASE}/releases`, payload),
  remove: (id) => http.del(`${BASE}/releases/${id}`),
};

export const financeApi = {
  calendar: (year, month) => http.get(`${BASE}/calendar`, { year, month }),
  revenue: () => http.get(`${BASE}/revenue`),
  dashboard: () => http.get(`${BASE}/dashboard`),
  addPayment: (payload) => http.post(`${BASE}/payments`, payload),
};

export const plansApi = {
  list: () => http.get(`${BASE}/plans`),
  create: (payload) => http.post(`${BASE}/plans`, payload),
  update: (id, payload) => http.put(`${BASE}/plans/${id}`, payload),
  remove: (id) => http.del(`${BASE}/plans/${id}`),
};

export { ApiError, getToken, setToken, onUnauthorized } from "./client";
