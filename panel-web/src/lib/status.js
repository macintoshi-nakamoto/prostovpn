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
