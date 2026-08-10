import { useCallback, useState } from "react";
import { usersApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import {
  ago,
  bytes,
  date,
  dateTime,
  days,
  flag,
  initials,
  money,
  trafficLimit,
} from "../../lib/format";
import { platformLabel, trafficColor, userStatus } from "../../lib/status";
import {
  Avatar,
  Bar,
  Button,
  Card,
  Chip,
  Copyable,
  Drawer,
  Empty,
  ErrorBox,
  KV,
  Loading,
  Section,
  StatusDot,
  Tile,
  confirmDialog,
} from "../../ui";
import { UserControls } from "./UserControls";

const TABS = [
  { id: "overview", label: "Обзор" },
  { id: "payments", label: "Оплаты" },
  { id: "sessions", label: "Сессии" },
  { id: "servers", label: "Серверы" },
];

export function UserDrawer({ userId, plans, onClose, onChanged }) {
  const [tab, setTab] = useState("overview");
  const { data: user, loading, error, reload, setData } = useAsync(() => usersApi.get(userId), [userId]);

  // Действия возвращают карточку целиком — подставляем её сразу, без
  // повторного запроса, и отдельно освежаем список за спиной.
  const applyResult = useCallback(
    (updated) => {
      if (updated) setData(updated);
      onChanged?.();
    },
    [setData, onChanged],
  );

  const status = user ? userStatus(user.status) : null;

  return (
    <Drawer
      onClose={onClose}
      head={
        user ? (
          <>
            <Avatar>{initials(user.name, user.login)}</Avatar>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{user.name || user.login}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 3 }}>
                <StatusDot color={status.color} label={status.label} glow={user.isOnline} />
                <span className="gd-mono" style={{ fontSize: 12, color: "var(--gd-faint)" }}>
                  {user.publicId}
                </span>
              </div>
            </div>
          </>
        ) : (
          <div style={{ fontSize: 16, fontWeight: 600 }}>Пользователь</div>
        )
      }
    >
      {loading && !user && <Loading />}
      <ErrorBox error={error} onRetry={reload} />

      {user && (
        <>
          <div className="gd-tiles" style={{ gridTemplateColumns: "repeat(2, minmax(0,1fr))" }}>
            <Tile
              label={user.planName ? `Тариф «${user.planName}»` : "Без тарифа"}
              value={Number(user.price) > 0 ? money(user.price, user.currency) : "—"}
              sub={user.periodDays ? `за ${days(user.periodDays)}` : null}
            />
            <Tile
              label={user.expiresAt ? "Оплачено до" : "Подписка"}
              value={user.expiresAt ? date(user.expiresAt) : "нет"}
              sub={user.daysLeft != null ? `осталось ${days(user.daysLeft)}` : null}
            />
          </div>

          <Card pad>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <div style={{ fontSize: 20, fontWeight: 700 }} className="gd-num">
                {bytes(user.trafficUsedBytes)}
              </div>
              <div style={{ color: "var(--gd-dim)", fontSize: 13 }}>
                из {trafficLimit(user.trafficLimitBytes)}
              </div>
              {user.trafficPct != null && (
                <div style={{ marginLeft: "auto", fontSize: 13, color: trafficColor(user.trafficPct) }}>
                  {user.trafficPct}%
                </div>
              )}
            </div>
            {user.trafficLimitBytes != null && (
              <div style={{ marginTop: 10 }}>
                <Bar pct={user.trafficPct} color={trafficColor(user.trafficPct)} />
              </div>
            )}
            {user.trafficResetAt && (
              <div className="gd-tile-l" style={{ marginTop: 8 }}>
                Счётчик обнулён {dateTime(user.trafficResetAt)}
              </div>
            )}
          </Card>

          <div className="gd-tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`gd-tab${tab === t.id ? " active" : ""}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="gd-pane">
            {tab === "overview" && <Overview user={user} />}
            {tab === "payments" && <Payments user={user} />}
            {tab === "sessions" && <Sessions user={user} onChanged={applyResult} />}
            {tab === "servers" && <Servers user={user} />}
          </div>

          <UserControls user={user} plans={plans} onResult={applyResult} onDeleted={onClose} />
        </>
      )}
    </Drawer>
  );
}

function Overview({ user }) {
  return (
    <Card pad>
      <KV k="Публичный ID" mono>
        <Copyable text={user.publicId} />
      </KV>
      <KV k="Логин" mono>
        <Copyable text={user.login} />
      </KV>
      {user.passwordHint && (
        <KV k="Пароль" mono>
          <Copyable text={user.passwordHint} />
        </KV>
      )}
      {user.contact && <KV k="Контакт">{user.contact}</KV>}
      <KV k="Зарегистрирован">{dateTime(user.createdAt)}</KV>
      <KV k="Последний вход">{user.lastSeenAt ? ago(user.lastSeenAt) : "ни разу"}</KV>
      <KV k="Активных сессий">{user.sessionsCount}</KV>
      <KV k="Серверов выдано">{user.serversCount}</KV>
      <KV k="Оплачено всего">{money(user.paidTotal, user.currency)}</KV>
      {user.blockedReason && (
        <KV k="Причина блокировки">
          <span style={{ color: "var(--gd-neg)" }}>{user.blockedReason}</span>
        </KV>
      )}
      {user.note && <KV k="Заметка">{user.note}</KV>}
    </Card>
  );
}

function Payments({ user }) {
  if (!user.payments.length) return <Empty>Оплат пока не было</Empty>;

  return (
    <Card pad>
      <Section title="История оплат" sub={`Всего ${money(user.paidTotal, user.currency)}`}>
        <div className="gd-rows">
          {user.payments.map((payment) => (
            <div key={payment.id} className="gd-r">
              <div style={{ minWidth: 0 }}>
                <div className="amt">{money(payment.amount, payment.currency)}</div>
                <div className="gd-cellsub">{payment.comment || payment.method || "Оплата"}</div>
              </div>
              <div className="r">{dateTime(payment.paidAt)}</div>
            </div>
          ))}
        </div>
      </Section>

      {user.subscriptions.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <Section title="Периоды подписки">
            <div className="gd-rows">
              {user.subscriptions.map((sub) => (
                <div key={sub.id} className="gd-r">
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>
                      {sub.plan} · {money(sub.price, sub.currency)}
                    </div>
                    <div className="gd-cellsub">
                      {date(sub.startsAt)} — {date(sub.expiresAt)} ({days(sub.periodDays)})
                    </div>
                  </div>
                  <div className="r">
                    {sub.isCancelled ? (
                      <Chip color="var(--gd-neg)">отменена</Chip>
                    ) : sub.autoRenew ? (
                      <Chip color="var(--gd-pos)">продлевается</Chip>
                    ) : (
                      <Chip>без продления</Chip>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>
      )}
    </Card>
  );
}

function Sessions({ user, onChanged }) {
  const [busy, setBusy] = useState(null);
  if (!user.sessions.length) return <Empty>Входов пока не было</Empty>;

  const kill = async (session) => {
    const ok = await confirmDialog({
      title: "Завершить сессию?",
      message: "Приложение на этом устройстве попросит войти заново.",
      confirmText: "Завершить",
      danger: true,
    });
    if (!ok) return;
    setBusy(session.id);
    try {
      await usersApi.killSession(user.id, session.id);
      const fresh = await usersApi.get(user.id);
      onChanged(fresh);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card pad>
      <div className="gd-rows">
        {user.sessions.map((session) => (
          <div key={session.id} className="gd-r">
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
                {platformLabel(session.platform)}
                {session.appVersion && <span className="gd-chip">{session.appVersion}</span>}
                {session.isOnline && <Chip color="var(--gd-pos)">онлайн</Chip>}
                {session.revokedAt && <Chip color="var(--gd-faint)">завершена</Chip>}
              </div>
              <div className="gd-cellsub">
                {session.ip || "адрес неизвестен"} · вход {dateTime(session.createdAt)}
              </div>
            </div>
            <div className="r" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {ago(session.lastSeenAt)}
              {!session.revokedAt && (
                <Button size="sm" variant="danger" disabled={busy === session.id} onClick={() => kill(session)}>
                  Завершить
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Servers({ user }) {
  const live = user.keys.filter((k) => !k.revokedAt);
  if (!live.length) return <Empty>Ключей на серверах нет</Empty>;

  return (
    <Card pad>
      <Section title="Ключи на серверах" sub="Клиент видит только страну — ни адреса, ни ключа">
        <div className="gd-rows">
          {live.map((key) => (
            <div key={key.id} className="gd-r">
              <span style={{ fontSize: 18 }}>{flag(key.countryCode)}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>
                  {key.country || key.serverName}
                  {key.city ? `, ${key.city}` : ""}
                </div>
                <div className="gd-cellsub gd-mono">
                  {key.address || "общий ключ"} · {key.serverName}
                </div>
              </div>
              <div className="r">
                {bytes(key.rxBytes + key.txBytes)}
                <div className="gd-cellsub">
                  {key.lastHandshakeAt ? ago(key.lastHandshakeAt) : "не подключался"}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Section>
    </Card>
  );
}
