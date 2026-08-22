import { useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, RotateCw, Send, Undo2 } from "lucide-react";
import { ordersApi } from "../../lib/api";
import { useAsync, useDebounced } from "../../lib/hooks";
import { ago, dateTime, money, num } from "../../lib/format";
import {
  ORDER_STATUS_FILTERS,
  deliveryStatus,
  orderStatus,
  webhookResult,
} from "../../lib/status";
import {
  Button,
  Card,
  CellName,
  Chip,
  Copyable,
  Dot,
  ErrorBox,
  PageHead,
  SearchInput,
  Section,
  Table,
  Tile,
  confirmDialog,
  promptDialog,
} from "../../ui";

const kopecks = (value, currency) => money(Number(value || 0) / 100, currency);

// Способ оплаты человеческими словами. Незнакомый код показываем как есть:
// новый способ на стороне провайдера не должен превращаться в прочерк.
const PAY_METHODS = {
  sbp: "СБП",
  crypto: "Криптовалюта",
  card: "Карта",
  sberpay: "SberPay",
};

/**
 * Заказы с сайта.
 *
 * Раздел открывают с одним вопросом: «человек заплатил, а доступа нет — где
 * встало?». Поэтому в строке видно всё звено сразу: статус заказа, дошло ли
 * уведомление от провайдера, создалась ли учётка и ушло ли письмо. Внизу —
 * сырой поток уведомлений, по которому видно, на чьей стороне проблема.
 */
export function OrdersPage() {
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const debounced = useDebounced(query, 300);

  const orders = useAsync(
    () => ordersApi.list({ status: tab, q: debounced || undefined }),
    [tab, debounced],
  );
  const deliveries = useAsync(() => ordersApi.deliveries({ only_problems: true }), []);
  const events = useAsync(() => ordersApi.events({ limit: 50 }), []);

  const rows = orders.data?.items || [];
  const stats = orders.data?.stats;

  const reloadAll = () => {
    orders.reload(true);
    deliveries.reload(true);
    events.reload(true);
  };

  const fulfil = async (row) => {
    const ok = await confirmDialog({
      title: "Выдать доступ вручную?",
      message:
        `Заказ на ${kopecks(row.amountKopecks, row.currency)} будет отмечен оплаченным, ` +
        `${row.email} получит учётку и письмо. Убедитесь, что деньги действительно пришли — ` +
        "это выдача подписки без подтверждения от провайдера, и она попадёт в журнал.",
      confirmText: "Выдать",
    });
    if (!ok) return;
    setBusy(row.id);
    setNotice(null);
    try {
      await ordersApi.fulfil(row.id);
      setNotice(`Заказ ${row.id.slice(0, 8)} выдан`);
      reloadAll();
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(null);
    }
  };

  const refund = async (row) => {
    const reason = await promptDialog({
      title: "Оформить возврат?",
      message:
        "Подписка будет отменена, пиры сняты с серверов. Деньги возвращаются на стороне " +
        "платёжного сервиса — здесь фиксируется только следствие.",
      placeholder: "Причина: например, обращение клиента",
      confirmText: "Оформить",
      danger: true,
    });
    if (reason === null) return;
    setBusy(row.id);
    setNotice(null);
    try {
      await ordersApi.refund(row.id, reason || undefined);
      setNotice(`По заказу ${row.id.slice(0, 8)} оформлен возврат`);
      reloadAll();
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(null);
    }
  };

  const retryDelivery = async (job) => {
    setBusy(`d${job.id}`);
    setNotice(null);
    try {
      const updated = await ordersApi.retryDelivery(job.id);
      setNotice(updated.sentAt ? "Отправлено" : `Снова не ушло: ${updated.lastError || "—"}`);
      deliveries.reload(true);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(null);
    }
  };

  const columns = [
    {
      key: "order",
      title: "Заказ",
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <Dot color={orderStatus(row.status).color} />
          <CellName title={row.email} sub={`${row.id.slice(0, 8)} · ${orderStatus(row.status).label}`} />
        </div>
      ),
    },
    {
      key: "plan",
      title: "Тариф",
      render: (row) => (
        <CellName
          title={row.planName || row.planCode}
          sub={row.isRenewal ? "продление" : "первая покупка"}
        />
      ),
    },
    {
      key: "amount",
      title: "Сумма",
      num: true,
      // Способ под суммой: у Platega через один адрес идут и СБП, и
      // криптовалюта, и в спорном платеже различить их больше нечем.
      render: (row) => (
        <CellName
          title={kopecks(row.amountKopecks, row.currency)}
          sub={PAY_METHODS[row.paymentMethod] || row.paymentMethod || row.provider || "—"}
        />
      ),
    },
    {
      key: "user",
      title: "Учётка",
      render: (row) =>
        row.userId ? (
          <Link to={`/users/${row.userId}`} style={{ color: "inherit" }}>
            <span className="gd-mono" style={{ fontSize: 12.5 }}>
              {row.userLogin}
            </span>
          </Link>
        ) : (
          <span style={{ color: "var(--gd-faint)" }}>—</span>
        ),
    },
    {
      key: "delivery",
      title: "Письмо",
      render: (row) => {
        const state = deliveryStatus(row.deliveryStatus);
        if (!state) return <span style={{ color: "var(--gd-faint)" }}>—</span>;
        return <Chip color={state.color}>{state.label}</Chip>;
      },
    },
    {
      key: "created",
      title: "Создан",
      render: (row) => (
        <span style={{ fontSize: 12.5, color: "var(--gd-dim)" }} title={dateTime(row.createdAt)}>
          {ago(row.createdAt)}
        </span>
      ),
    },
    {
      key: "actions",
      title: "",
      render: (row) => (
        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
          {row.status !== "paid" && row.status !== "refunded" && (
            <Button
              size="sm"
              disabled={busy === row.id}
              title="Выдать вручную"
              onClick={(e) => {
                e.stopPropagation();
                fulfil(row);
              }}
            >
              <CheckCircle2 size={14} />
            </Button>
          )}
          {row.status === "paid" && (
            <Button
              size="sm"
              variant="danger"
              disabled={busy === row.id}
              title="Оформить возврат"
              onClick={(e) => {
                e.stopPropagation();
                refund(row);
              }}
            >
              <Undo2 size={14} />
            </Button>
          )}
        </div>
      ),
    },
  ];

  const problemJobs = deliveries.data || [];
  const eventRows = events.data || [];

  return (
    <div className="gd-root">
      <PageHead title="Заказы" sub="Оплаты с сайта и выдача доступов">
        <Button onClick={reloadAll}>
          <RotateCw size={15} />
          Обновить
        </Button>
      </PageHead>

      {stats && (
        <div
          className="gd-tiles"
          style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))", marginBottom: 16 }}
        >
          <Tile label="Оплачено" value={num(stats.paid)} dot="var(--gd-pos)" />
          <Tile label="Ждут оплаты" value={num(stats.pending)} dot="var(--gd-warn)" />
          <Tile
            label="Не доставлено"
            value={num(stats.undelivered)}
            dot={stats.undelivered ? "var(--gd-neg)" : undefined}
            sub={stats.undelivered ? "клиент заплатил и ждёт" : undefined}
          />
          <Tile label="Выручка сайта" value={kopecks(stats.revenueKopecks, stats.currency)} />
        </div>
      )}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <div className="gd-tabs">
          {ORDER_STATUS_FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`gd-tab${tab === item.id ? " active" : ""}`}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Почта, номер заказа или платежа"
          style={{ flex: "1 1 260px", maxWidth: 400 }}
        />
      </div>

      {notice && (
        <div
          className="gd-error"
          style={{ marginBottom: 12, background: "var(--gd-card)", color: "var(--gd-dim)" }}
        >
          {notice}
        </div>
      )}
      <ErrorBox error={orders.error} onRetry={orders.reload} />

      <Card className="gd-table-card">
        <Table
          columns={columns}
          rows={rows}
          keyOf={(row) => row.id}
          loading={orders.loading && !orders.data}
          empty="Заказов нет"
        />
      </Card>

      {problemJobs.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <Section
            title="Недоставленные письма"
            sub="Деньги получены, доступ до человека не дошёл"
          />
          <Card className="gd-table-card">
            <Table
              columns={[
                {
                  key: "target",
                  title: "Кому",
                  render: (job) => (
                    <CellName title={job.target} sub={`${job.channel} · попыток ${job.attempts}`} />
                  ),
                },
                {
                  key: "error",
                  title: "Что говорит отправитель",
                  render: (job) => (
                    <span style={{ fontSize: 12.5, color: "var(--gd-neg)", whiteSpace: "normal" }}>
                      {job.lastError || "ещё не пробовали"}
                    </span>
                  ),
                },
                {
                  key: "when",
                  title: "Создано",
                  render: (job) => (
                    <span style={{ fontSize: 12.5, color: "var(--gd-dim)" }}>{ago(job.createdAt)}</span>
                  ),
                },
                {
                  key: "actions",
                  title: "",
                  render: (job) => (
                    <div style={{ display: "flex", justifyContent: "flex-end" }}>
                      <Button size="sm" disabled={busy === `d${job.id}`} onClick={() => retryDelivery(job)}>
                        <Send size={14} />
                        Отправить снова
                      </Button>
                    </div>
                  ),
                },
              ]}
              rows={problemJobs}
              keyOf={(job) => job.id}
              empty="Всё доставлено"
            />
          </Card>
        </div>
      )}

      <div style={{ marginTop: 24 }}>
        <Section
          title="Уведомления провайдера"
          sub="Сырой поток: приходило ли, сколько раз и чем закончилось"
        />
      </div>
      <Card className="gd-table-card">
        <Table
          columns={[
            {
              key: "event",
              title: "Событие",
              render: (row) => (
                <CellName
                  title={<Copyable text={row.eventId}>{row.eventId.slice(0, 28)}</Copyable>}
                  sub={`${row.provider} · ${row.kind || "—"}`}
                />
              ),
            },
            {
              key: "order",
              title: "Заказ",
              render: (row) => (
                <span className="gd-mono" style={{ fontSize: 12.5, color: "var(--gd-dim)" }}>
                  {row.orderId ? row.orderId.slice(0, 8) : "—"}
                </span>
              ),
            },
            {
              key: "result",
              title: "Итог",
              render: (row) => (
                <Chip color={row.result === "ok" ? "var(--gd-pos)" : "var(--gd-dim)"}>
                  {webhookResult(row.result)}
                </Chip>
              ),
            },
            {
              key: "at",
              title: "Получено",
              render: (row) => (
                <span style={{ fontSize: 12.5, color: "var(--gd-dim)" }}>{dateTime(row.receivedAt)}</span>
              ),
            },
          ]}
          rows={eventRows}
          keyOf={(row) => row.eventId}
          loading={events.loading && !events.data}
          empty="Уведомлений ещё не было"
        />
      </Card>
    </div>
  );
}
