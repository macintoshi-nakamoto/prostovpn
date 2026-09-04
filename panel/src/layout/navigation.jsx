import {
  BarChart3,
  CalendarDays,
  Download,
  Filter,
  Route,
  KeyRound,
  Receipt,
  ScrollText,
  Server,
  Tags,
  Users,
} from "lucide-react";

export const NAV_GROUPS = [
  {
    label: "Обзор",
    items: [
      { to: "/", label: "Сводка", title: "Сводка", icon: BarChart3, end: true },
      { to: "/funnel", label: "Воронка", title: "Воронка: от регистрации до оплаты", icon: Filter },
      { to: "/calendar", label: "Календарь", title: "Календарь прибыли", icon: CalendarDays },
    ],
  },
  {
    label: "Клиенты",
    items: [
      { to: "/users", label: "Пользователи", title: "Пользователи", icon: Users },
      { to: "/orders", label: "Заказы", title: "Заказы", icon: Receipt },
      { to: "/plans", label: "Тарифы", title: "Тарифы", icon: Tags },
    ],
  },
  {
    label: "Инфраструктура",
    items: [
      { to: "/servers", label: "Серверы", title: "Серверы", icon: Server },
      { to: "/keys", label: "Ключи", title: "Аккаунты на серверах", icon: KeyRound },
      { to: "/releases", label: "Версии", title: "Версии приложения", icon: Download },
      { to: "/tunnel-file", label: "Файл обхода", title: "Файл обхода", icon: Route },
      { to: "/audit", label: "Журнал", title: "Журнал", icon: ScrollText },
    ],
  },
];

export const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

export const BOTTOM_NAV = NAV_ITEMS.filter((item) =>
  ["/users", "/orders", "/calendar", "/servers"].includes(item.to),
);

export function titleFor(pathname) {
  const exact = NAV_ITEMS.find((item) => item.to === pathname);
  if (exact) return exact.title;
  const prefix = NAV_ITEMS.filter((item) => item.to !== "/" && pathname.startsWith(item.to)).sort(
    (a, b) => b.to.length - a.to.length,
  )[0];
  return prefix?.title || "Панель";
}
