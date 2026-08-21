import { ago, bytes, date, days, money, trafficLimit } from "../../lib/format";
import { trafficColor, userStatus } from "../../lib/status";
import { Bar, CellName, Chip, Dot, StatusDot } from "../../ui";

/**
 * Колонки списка пользователей.
 *
 * Набор выбран так, чтобы по строке было видно всё, за чем сюда приходят:
 * кто это, сколько платит, сколько осталось и не пора ли выключать.
 */
export const userColumns = [
  {
    key: "user",
    title: "Клиент",
    sortKey: "name",
    render: (u) => (
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <Dot color={userStatus(u.status).color} glow={u.isOnline} />
        <CellName title={u.name || u.login} sub={u.login} />
        {u.isFree && <Chip color="var(--gd-gold)">фри</Chip>}
      </div>
    ),
  },
  {
    key: "publicId",
    title: "ID",
    render: (u) => (
      <span className="gd-mono" style={{ fontSize: 12.5, color: "var(--gd-dim)" }}>
        {u.publicId}
      </span>
    ),
  },
  {
    key: "plan",
    title: "Тариф",
    render: (u) =>
      u.plan ? (
        <CellName title={u.planName || u.plan} sub={u.periodDays ? `${u.periodDays} дн.` : null} />
      ) : (
        <span style={{ color: "var(--gd-faint)" }}>—</span>
      ),
  },
  {
    key: "price",
    title: "Платит",
    sortKey: "price",
    num: true,
    render: (u) => (Number(u.price) > 0 ? money(u.price, u.currency) : <span style={{ color: "var(--gd-faint)" }}>—</span>),
  },
  {
    key: "traffic",
    title: "Трафик",
    sortKey: "traffic",
    width: 170,
    render: (u) => (
      <div style={{ minWidth: 120 }}>
        <div style={{ fontSize: 12.5, display: "flex", justifyContent: "space-between", gap: 8 }}>
          <span className="gd-num">{bytes(u.trafficUsedBytes)}</span>
          <span style={{ color: "var(--gd-faint)" }}>{trafficLimit(u.trafficLimitBytes)}</span>
        </div>
        {/* Безлимит рисовать полосой нечем — и не надо: заполнять нечего. */}
        {u.trafficLimitBytes != null && (
          <div style={{ marginTop: 6 }}>
            <Bar pct={u.trafficPct} color={trafficColor(u.trafficPct)} />
          </div>
        )}
      </div>
    ),
  },
  {
    key: "expires",
    title: "Оплачено до",
    sortKey: "expires",
    render: (u) =>
      u.expiresAt ? (
        <CellName
          title={date(u.expiresAt)}
          sub={u.daysLeft != null ? `осталось ${days(u.daysLeft)}` : null}
        />
      ) : (
        <span style={{ color: "var(--gd-faint)" }}>не оплачен</span>
      ),
  },
  {
    key: "paid",
    title: "Всего оплат",
    sortKey: "paid",
    num: true,
    render: (u) => money(u.paidTotal, u.currency),
  },
  {
    key: "status",
    title: "Статус",
    render: (u) => {
      const meta = userStatus(u.status);
      return (
        <div style={{ minWidth: 0 }}>
          <StatusDot color={meta.color} label={meta.label} glow={u.status === "online"} />
          {/* Когда подключался в последний раз — это первое, что спрашивают
              про человека со статусом «оффлайн». */}
          {u.status === "offline" && (
            <div className="gd-cellsub">
              {u.lastHandshakeAt ? ago(u.lastHandshakeAt) : "ни разу не подключался"}
            </div>
          )}
        </div>
      );
    },
  },
];
