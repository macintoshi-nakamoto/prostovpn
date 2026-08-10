import { BarChart3, CalendarDays, Download, KeyRound, Server, Tags, Users } from "lucide-react";

// Разделы панели. Заголовок страницы берётся отсюда же — держать его
// вторым списком значит однажды забыть обновить один из них.
export const NAV_GROUPS = [
  {
    label: "Обзор",
    items: [
      { to: "/", label: "Сводка", title: "Сводка", icon: BarChart3, end: true },
      { to: "/calendar", label: "Календарь", title: "Календарь прибыли", icon: CalendarDays },
    ],
  },
  {
    label: "Клиенты",
    items: [
      { to: "/users", label: "Пользователи", title: "Пользователи", icon: Users },
      { to: "/plans", label: "Тарифы", title: "Тарифы", icon: Tags },
    ],
  },
  {
    label: "Инфраструктура",
    items: [
      { to: "/servers", label: "Серверы", title: "Серверы", icon: Server },
      { to: "/keys", label: "Ключи", title: "Аккаунты на серверах", icon: KeyRound },
      { to: "/releases", label: "Версии", title: "Версии приложения", icon: Download },
    ],
  },
];

export const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

// Быстрые разделы для нижнего бара на телефоне — ежедневный набор.
export const BOTTOM_NAV = NAV_ITEMS.filter((item) =>
  ["/users", "/calendar", "/servers", "/keys"].includes(item.to),
);

export function titleFor(pathname) {
  // Сначала точное совпадение, потом самый длинный подходящий префикс:
  // «/» иначе выигрывал бы у всех.
  const exact = NAV_ITEMS.find((item) => item.to === pathname);
  if (exact) return exact.title;
  const prefix = NAV_ITEMS.filter((item) => item.to !== "/" && pathname.startsWith(item.to)).sort(
    (a, b) => b.to.length - a.to.length,
  )[0];
  return prefix?.title || "Панель";
}
