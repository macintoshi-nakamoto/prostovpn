// Статусы пользователя, ключа и сервера: цвет и подпись в одном месте.
// Совпадение цвета и слова на всех экранах важнее краткости импорта.

export const USER_STATUS = {
  active: { label: "Активен", color: "var(--gd-pos)" },
  paused: { label: "Отключён", color: "var(--gd-warn)" },
  blocked: { label: "Заблокирован", color: "var(--gd-neg)" },
  expired: { label: "Не оплачен", color: "var(--gd-faint)" },
  traffic: { label: "Трафик исчерпан", color: "var(--gd-info)" },
};

export function userStatus(status) {
  return USER_STATUS[status] || { label: status || "—", color: "var(--gd-faint)" };
}

export const USER_STATUS_FILTERS = [
  { id: "all", label: "Все" },
  { id: "active", label: "Активные" },
  { id: "expired", label: "Не оплачены" },
  { id: "traffic", label: "Трафик" },
  { id: "paused", label: "Отключены" },
  { id: "blocked", label: "Бан" },
];

/** Цвет полосы расхода: к лимиту ближе — тревожнее. */
export function trafficColor(pct) {
  if (pct == null) return "var(--gd-info)";
  if (pct >= 100) return "var(--gd-neg)";
  if (pct >= 80) return "var(--gd-warn)";
  return "var(--gd-pos)";
}

// Заказы с сайта. Цвета те же, что у статусов пользователя: «оплачено» и
// «активен» на соседних экранах должны быть одного зелёного.
export const ORDER_STATUS = {
  pending: { label: "Ждёт оплаты", color: "var(--gd-warn)" },
  paid: { label: "Оплачен", color: "var(--gd-pos)" },
  failed: { label: "Отклонён", color: "var(--gd-neg)" },
  refunded: { label: "Возврат", color: "var(--gd-violet)" },
  expired: { label: "Просрочен", color: "var(--gd-faint)" },
};

export function orderStatus(status) {
  return ORDER_STATUS[status] || { label: status || "—", color: "var(--gd-faint)" };
}

export const ORDER_STATUS_FILTERS = [
  { id: "all", label: "Все" },
  { id: "pending", label: "Ждут оплаты" },
  { id: "paid", label: "Оплачены" },
  { id: "failed", label: "Отклонены" },
  { id: "refunded", label: "Возвраты" },
  { id: "expired", label: "Просрочены" },
];

// Доставка учётки. «Не ушло» — единственное состояние, ради которого этот
// столбец вообще существует, поэтому оно красное и заметное.
export const DELIVERY_STATUS = {
  sent: { label: "Отправлено", color: "var(--gd-pos)" },
  pending: { label: "В очереди", color: "var(--gd-warn)" },
  failed: { label: "Не ушло", color: "var(--gd-neg)" },
};

export function deliveryStatus(status) {
  return DELIVERY_STATUS[status] || null;
}

// Итог обработки уведомления провайдера. Расшифровка нужна: коды пишет
// backend, а читает их человек в панели.
export const WEBHOOK_RESULTS = {
  ok: "Выдано",
  duplicate: "Повтор, пропущен",
  unknown_order: "Заказ не найден",
  amount_mismatch: "Сумма не совпала",
  amount_unverified: "Выдано, сумма не подтверждена",
  ignored: "Пропущено",
  refunded: "Возврат",
  error: "Ошибка обработки",
};

export function webhookResult(code) {
  return WEBHOOK_RESULTS[code] || code || "—";
}

export const PLATFORM_LABELS = {
  windows: "Windows",
  android: "Android",
  ios: "iOS",
  macos: "macOS",
  linux: "Linux",
};

export function platformLabel(platform) {
  return PLATFORM_LABELS[platform] || platform || "—";
}
