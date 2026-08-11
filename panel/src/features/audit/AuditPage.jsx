import { useState } from "react";
import { Link } from "react-router-dom";
import { auditApi } from "../../lib/api";
import { useAsync, useDebounced } from "../../lib/hooks";
import { ago, dateTime } from "../../lib/format";
import { Card, CellName, Chip, ErrorBox, PageHead, SearchInput, Table } from "../../ui";

// Человеческие названия действий. Коды пишет backend, читает их человек, и
// «user.password_reveal» в списке — это работа переводчика, отданная
// администратору.
const ACTION_LABELS = {
  "user.create": { label: "Создан клиент", color: "var(--gd-pos)" },
  "user.renew": { label: "Продление", color: "var(--gd-pos)" },
  "user.update": { label: "Изменены данные" },
  "user.enable": { label: "Включён" },
  "user.disable": { label: "Отключён", color: "var(--gd-warn)" },
  "user.block": { label: "Заблокирован", color: "var(--gd-neg)" },
  "user.unblock": { label: "Разблокирован" },
  "user.delete": { label: "Удалён", color: "var(--gd-neg)" },
  "user.password_reset": { label: "Сброшен пароль", color: "var(--gd-warn)" },
  "user.password_reveal": { label: "Показан пароль", color: "var(--gd-neg)" },
  "user.extend": { label: "Продление" },
  "user.traffic_limit": { label: "Изменён лимит" },
  "user.traffic_reset": { label: "Обнулён трафик" },
  "order.fulfil_manual": { label: "Выдача вручную", color: "var(--gd-warn)" },
  "order.refund": { label: "Возврат", color: "var(--gd-violet)" },
  "order.refund_manual": { label: "Возврат вручную", color: "var(--gd-violet)" },
  "order.amount_mismatch": { label: "Сумма не совпала", color: "var(--gd-neg)" },
  "delivery.retry": { label: "Повтор письма" },
  "session.kill": { label: "Сессия закрыта" },
  "server.create": { label: "Добавлен сервер" },
  "server.delete": { label: "Удалён сервер", color: "var(--gd-neg)" },
  "key.revoke": { label: "Отозван ключ", color: "var(--gd-warn)" },
  "plan.create": { label: "Создан тариф" },
  "plan.update": { label: "Изменён тариф" },
  "plan.delete": { label: "Удалён тариф", color: "var(--gd-neg)" },
};

function actionInfo(action) {
  return ACTION_LABELS[action] || { label: action };
}

/**
 * Журнал действий администраторов.
 *
 * Только чтение: журнал, который чистится из той же панели, журналом не
 * является. Разбирательство «кто и когда смотрел пароль этого клиента»
 * случается ровно тогда, когда кнопка «очистить» уже была бы нажата.
 */
export function AuditPage() {
  const [query, setQuery] = useState("");
  const [action, setAction] = useState("");
  const debounced = useDebounced(query, 300);

  const actions = useAsync(() => auditApi.actions(), []);
  const entries = useAsync(
    () => auditApi.list({ action: action || undefined, target: debounced || undefined }),
    [action, debounced],
  );

  const rows = entries.data || [];

  const columns = [
    {
      key: "action",
      title: "Действие",
      render: (row) => {
        const info = actionInfo(row.action);
        return <Chip color={info.color || "var(--gd-dim)"}>{info.label}</Chip>;
      },
    },
    {
      key: "target",
      title: "Над кем",
      render: (row) =>
        row.target ? (
          // Публичный id клиента выглядит как PV-XXXX-XXXX; всё остальное —
          // это заказы и сессии, для них ссылки нет.
          /^PV-/.test(row.target) ? (
            <Link to={`/users?q=${encodeURIComponent(row.target)}`} style={{ color: "inherit" }}>
              <span className="gd-mono" style={{ fontSize: 12.5 }}>
                {row.target}
              </span>
            </Link>
          ) : (
            <span className="gd-mono" style={{ fontSize: 12.5, color: "var(--gd-dim)" }}>
              {row.target}
            </span>
          )
        ) : (
          <span style={{ color: "var(--gd-faint)" }}>—</span>
        ),
    },
    {
      key: "detail",
      title: "Подробности",
      render: (row) => (
        <span style={{ fontSize: 12.5, color: "var(--gd-dim)", whiteSpace: "normal" }}>
          {row.detail || "—"}
        </span>
      ),
    },
    {
      key: "admin",
      title: "Кто",
      render: (row) => (
        <CellName title={row.adminLogin || "система"} sub={row.adminId ? `#${row.adminId}` : "автоматически"} />
      ),
    },
    {
      key: "at",
      title: "Когда",
      render: (row) => (
        <span style={{ fontSize: 12.5, color: "var(--gd-dim)" }} title={dateTime(row.createdAt)}>
          {ago(row.createdAt)}
        </span>
      ),
    },
  ];

  return (
    <div className="gd-root">
      <PageHead title="Журнал" sub="Что делали с клиентами и заказами" />

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <select
          className="gd-select"
          value={action}
          onChange={(e) => setAction(e.target.value)}
          style={{ width: "auto", minWidth: 200 }}
        >
          <option value="">Все действия</option>
          {(actions.data || []).map((code) => (
            <option key={code} value={code}>
              {actionInfo(code).label}
            </option>
          ))}
        </select>
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Публичный id клиента или номер заказа"
          style={{ flex: "1 1 260px", maxWidth: 400 }}
        />
      </div>

      <ErrorBox error={entries.error} onRetry={entries.reload} />

      <Card className="gd-table-card">
        <Table
          columns={columns}
          rows={rows}
          keyOf={(row) => row.id}
          loading={entries.loading && !entries.data}
          empty="Записей нет"
        />
      </Card>
    </div>
  );
}
