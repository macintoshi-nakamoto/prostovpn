import { useCallback, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { transfersApi, usersApi } from "../../lib/api";
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
import { orderStatus, platformLabel, trafficColor, userStatus } from "../../lib/status";
import {
  Avatar,
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
  { id: "transfers", label: "Дни" },
  { id: "orders", label: "Заказы" },
  { id: "sessions", label: "Устройства" },
  { id: "ios", label: "iPhone" },
  { id: "servers", label: "Серверы" },
];

function PasswordRow({ user }) {
  const [password, setPassword] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!user.hasPassword) {
    return (
      <KV k="Пароль">
        <span style={{ color: "var(--gd-faint)" }}>
          недоступен — учётка старше шифрования, остаётся сбросить
        </span>
      </KV>
    );
  }

  const reveal = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await usersApi.revealPassword(user.id);
      setPassword(result.password);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <KV k="Пароль" mono>
      {password ? (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
          <Copyable text={password} />
          <Button size="sm" onClick={() => setPassword(null)} title="Скрыть">
            <EyeOff size={13} />
          </Button>
        </span>
      ) : (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
          <span style={{ letterSpacing: 3, color: "var(--gd-dim)" }}>••••••••</span>
          <Button size="sm" disabled={busy} onClick={reveal}>
            <Eye size={13} />
            {busy ? "…" : "Показать"}
          </Button>
        </span>
      )}
      {error && (
        <div style={{ color: "var(--gd-neg)", fontSize: 12, marginTop: 6, whiteSpace: "normal" }}>
          {error}
        </div>
      )}
    </KV>
  );
}

export function UserDrawer({ userId, plans, onClose, onChanged }) {
  const [tab, setTab] = useState("overview");
  const { data: user, loading, error, reload, setData } = useAsync(() => usersApi.get(userId), [userId]);

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
                {user.isFree && <Chip color="var(--gd-gold)">бесплатно</Chip>}
                {user.isFrozen && <Chip color="var(--gd-info)">на паузе</Chip>}
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
              label={user.isFrozen ? "Хватит до" : user.expiresAt ? "Оплачено до" : "Подписка"}
              value={user.expiresAt ? date(user.expiresAt) : "нет"}
              sub={
                user.isFrozen
                  ? `на паузе с ${date(user.frozenAt)} · в запасе ${days(user.daysLeft || 0)}`
                  : user.daysLeft != null
                    ? `осталось ${days(user.daysLeft)}`
                    : null
              }
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
              <div className="gd-tile-l" style={{ marginTop: 8, whiteSpace: "normal" }}>
                {user.status === "traffic" ? (
                  <span style={{ color: "var(--gd-neg)" }}>
                    Лимит выбран — доступ закрыт, пиры сняты с узлов. Обнулите счётчик
                    или поднимите лимит, чтобы вернуть доступ.
                  </span>
                ) : (
                  <>Осталось {bytes(Math.max(0, user.trafficLimitBytes - user.trafficUsedBytes))}</>
                )}
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
            {tab === "transfers" && <Transfers user={user} />}
            {tab === "orders" && <Orders user={user} />}
            {tab === "sessions" && <Sessions user={user} onChanged={applyResult} />}
            {tab === "ios" && <IosKeys user={user} onChanged={applyResult} />}
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
      <PasswordRow user={user} />
      {user.email && (
        <KV k="Почта" mono>
          <Copyable text={user.email} />
        </KV>
      )}
      {user.contact && <KV k="Контакт">{user.contact}</KV>}
      <KV k="Подключение">
        {user.isOnline ? (
          <span style={{ color: "var(--gd-pos)" }}>подключён к VPN сейчас</span>
        ) : user.lastHandshakeAt ? (
          <>отключён · был {ago(user.lastHandshakeAt)}</>
        ) : (
          <span style={{ color: "var(--gd-faint)" }}>ни разу не подключался</span>
        )}
      </KV>
      <KV k="Приложение">
        {user.appOnline ? "открыто" : user.lastSeenAt ? ago(user.lastSeenAt) : "не запускалось"}
      </KV>
      <KV k="Зарегистрирован">{dateTime(user.createdAt)}</KV>
      <KV k="Последний вход">{user.lastLoginAt ? ago(user.lastLoginAt) : "ни разу"}</KV>
      <KV k="Устройств">
        {user.devicesUsed} из {user.deviceLimit}
      </KV>
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

function IosKeys({ user, onChanged }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const keys = user.iosKeys || [];
  const max = user.iosMaxKeys || 0;

  const used = new Set(keys.map((k) => k.slot)).size;

  const run = async (action, fn) => {
    setBusy(action);
    setError(null);
    try {
      const result = await fn();
      if (result) onChanged(result);
    } catch (err) {
      setError(err.message || "Не удалось выполнить");
    } finally {
      setBusy(null);
    }
  };

  const addKey = () => run("add", () => usersApi.iosAddKey(user.id));

  const removeKey = async (slot) => {
    const ok = await confirmDialog({
      title: `Удалить ключ ${slot}?`,
      message:
        "Пир уйдёт с узлов, ссылка перестанет работать сразу и не восстановится: " +
        "у ключа нет пароля, и вернуть можно только новый.",
      confirmText: "Удалить",
      danger: true,
    });
    if (!ok) return;
    return run(`del-${slot}`, () => usersApi.iosRemoveKey(user.id, slot));
  };

  const reissue = async () => {
    const ok = await confirmDialog({
      title: "Перевыпустить ключи?",
      message:
        "Все ссылки этой учётки сменятся разом — те, что уже вставлены в Amnezia, перестанут " +
        "работать. Так снимают утёкший ключ.",
      confirmText: "Перевыпустить",
      danger: true,
    });
    if (!ok) return;
    return run("reissue", () => usersApi.iosReissue(user.id));
  };

  if (!user.iosAccess) {
    return (
      <Card pad>
        <Section
          title="Ключей для iPhone нет"
          sub="Выдаётся первый ключ, остальные — кнопкой «Добавить ключ»"
        >
          {error && <div className="gd-error" style={{ marginBottom: 10 }}>{error}</div>}
          <Button
            variant="primary"
            disabled={busy === "enable"}
            onClick={() => run("enable", () => usersApi.iosEnable(user.id))}
          >
            {busy === "enable" ? "Выдаём…" : "Выдать ключ"}
          </Button>
        </Section>
      </Card>
    );
  }

  return (
    <Card pad>
      {error && <div className="gd-error" style={{ marginBottom: 10 }}>{error}</div>}

      {user.iosBlocked && (
        <div className="gd-cellsub" style={{ color: "var(--gd-neg)", marginBottom: 12 }}>
          Ключи отключены: пиры сняты с узлов, выдать себе новый в кабинете человек не может.
        </div>
      )}

      <Section
        title={`Ключи AmneziaVPN · ${used} из ${max}`}
        sub="По ключу на устройство — поделить один пир между телефонами нельзя"
        actions={
          <Button
            size="sm"
            variant="primary"
            disabled={busy === "add" || !user.iosCanAdd}
            onClick={addKey}
          >
            {busy === "add" ? "Создаём…" : "Добавить ключ"}
          </Button>
        }
      >
        {keys.length === 0 ? (
          <Empty>
            {user.iosBlocked
              ? "Ключи сняты — включите доступ, и они вернутся теми же"
              : "Ключей на узлах нет: подписка кончилась или узел не ответил"}
          </Empty>
        ) : (
          <div className="gd-rows">
            {keys.map((key) => (
              <div key={`${key.slot}-${key.serverId}`} className="gd-r">
                <span style={{ fontSize: 18, opacity: key.disconnected ? 0.5 : 1 }}>
                  {flag(key.countryCode)}
                </span>
                <div style={{ minWidth: 0, opacity: key.disconnected ? 0.7 : 1 }}>
                  <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
                    Ключ {key.slot} · {key.country || key.serverName}
                    {key.isConnected && <Chip color="var(--gd-pos)">в VPN</Chip>}
                    {key.disconnected && <Chip color="var(--gd-faint)">отключён</Chip>}
                  </div>
                  <div className="gd-cellsub" style={{ maxWidth: 320 }}>
                    {key.disconnected ? (
                      "отключён из кабинета · включается той же ссылкой"
                    ) : (
                      <Copyable text={key.vpnUrl}>ссылка vpn:// · скопировать</Copyable>
                    )}
                  </div>
                  <div className="gd-cellsub gd-mono">
                    {key.address || "без адреса"} · выдан {date(key.createdAt)}
                  </div>
                </div>
                <div className="r" style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div>
                    {bytes(key.trafficBytes)}
                    <div className="gd-cellsub">
                      {key.lastHandshakeAt ? ago(key.lastHandshakeAt) : "не подключался"}
                    </div>
                  </div>
                  {key.disconnected ? (
                    <Button
                      size="sm"
                      variant="on"
                      disabled={busy === `on-${key.slot}`}
                      onClick={() =>
                        run(`on-${key.slot}`, () => usersApi.iosEnableKey(user.id, key.slot))
                      }
                    >
                      Включить
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      disabled={busy === `off-${key.slot}`}
                      onClick={() =>
                        run(`off-${key.slot}`, () => usersApi.iosDisconnectKey(user.id, key.slot))
                      }
                    >
                      Отключить
                    </Button>
                  )}
                  {used > 1 && (
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={busy === `del-${key.slot}`}
                      onClick={() => removeKey(key.slot)}
                    >
                      Удалить
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <div style={{ marginTop: 18 }}>
        <Section title="Ключи целиком" sub="Действия на всю учётку, а не на один ключ">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {user.iosBlocked ? (
              <Button
                variant="on"
                disabled={busy === "enable"}
                onClick={() => run("enable", () => usersApi.iosEnable(user.id))}
              >
                Включить обратно
              </Button>
            ) : (
              <Button
                variant="danger"
                disabled={busy === "disable"}
                onClick={() => run("disable", () => usersApi.iosDisable(user.id))}
              >
                Отключить
              </Button>
            )}
            <Button disabled={busy === "reissue"} onClick={reissue}>
              Перевыпустить все
            </Button>
            <Button
              variant="danger"
              disabled={busy === "remove"}
              onClick={async () => {
                const ok = await confirmDialog({
                  title: "Убрать ключи совсем?",
                  message:
                    "Пиры уйдут с узлов, строки — из базы. После этого человек сможет выдать " +
                    "себе ключ заново в кабинете, и это будет уже другой ключ.",
                  confirmText: "Убрать",
                  danger: true,
                });
                if (ok) run("remove", () => usersApi.iosRemove(user.id));
              }}
            >
              Убрать доступ
            </Button>
          </div>
          <div className="gd-cellsub" style={{ marginTop: 10, whiteSpace: "normal" }}>
            «Отключить» снимает пиры, но оставляет ключи за учёткой: включение вернёт те же
            ссылки, и человеку не придётся ничего переставлять. «Перевыпустить» меняет ссылки —
            для утёкшего ключа. «Убрать доступ» удаляет всё вместе со строками.
          </div>
        </Section>
      </div>
    </Card>
  );
}

function Transfers({ user }) {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    let alive = true;
    transfersApi

      .list({ user_id: user.id })
      .then((data) => alive && setRows(data))
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, [user.id]);

  if (rows === null) return <Loading />;
  if (!rows.length) return <Empty>Переводов дней не было</Empty>;

  return (
    <Card pad>
      <Section title="Переводы дней" sub={`Всего ${rows.length}`}>
        <div className="gd-rows">
          {rows.map((row) => {
            const outgoing = row.fromId === user.id;
            return (
              <div key={row.id} className="gd-r">
                <div style={{ minWidth: 0 }}>
                  <div className="amt" style={{ color: outgoing ? "var(--gd-dim)" : "var(--gd-gold)" }}>
                    {outgoing ? "−" : "+"}
                    {row.days} дн.
                  </div>
                  <div className="gd-cellsub">
                    {outgoing ? `Кому: ${row.toLogin}` : `От: ${row.fromLogin}`}
                    {row.origin ? ` · ${ORIGIN_LABELS[row.origin] || row.origin}` : ""}
                  </div>
                </div>
                <div className="r">{dateTime(row.createdAt)}</div>
              </div>
            );
          })}
        </div>
      </Section>
    </Card>
  );
}

const ORIGIN_LABELS = { site: "сайт", bot: "бот", panel: "панель" };

function Orders({ user }) {
  const orders = user.orders || [];
  if (!orders.length) return <Empty>Заказов с сайта не было</Empty>;

  return (
    <Card pad>
      <Section title="Заказы с сайта" sub="Включая те, что не удалось выдать">
        <div className="gd-rows">
          {orders.map((order) => {
            const status = orderStatus(order.status);
            return (
              <div key={order.id} className="gd-r">
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5 }}>
                    {order.planName || order.planCode}
                    {order.isRenewal ? " · продление" : ""}
                  </div>
                  <div className="gd-tile-l">
                    {dateTime(order.createdAt)} · {order.id.slice(0, 8)}
                  </div>
                  {order.failureReason && (
                    <div
                      className="gd-tile-l"
                      style={{ color: "var(--gd-neg)", whiteSpace: "normal", marginTop: 2 }}
                    >
                      {order.failureReason}
                    </div>
                  )}
                </div>
                <div style={{ marginLeft: "auto", textAlign: "right" }}>
                  <div className="gd-num" style={{ fontSize: 14 }}>
                    {money(order.amountKopecks / 100, order.currency)}
                  </div>
                  <Chip color={status.color}>{status.label}</Chip>
                </div>
              </div>
            );
          })}
        </div>
      </Section>
    </Card>
  );
}

const PAY_METHODS = {
  platega: "СБП",
  yookassa: "Карта",
  cryptocloud: "Криптовалюта",
  mock: "Тестовая оплата",
  "панель": "Вручную",
  panel: "Вручную",
};

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
                <div className="gd-cellsub">{payment.comment || "Оплата"}</div>
                {(payment.method || payment.externalId) && (
                  <div className="gd-cellsub" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {payment.method && (
                      <span>{PAY_METHODS[String(payment.method).toLowerCase()] || payment.method}</span>
                    )}
                    {payment.externalId && (
                      <span className="gd-mono" style={{ fontSize: 11.5 }}>{payment.externalId}</span>
                    )}
                  </div>
                )}
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
  const [warning, setWarning] = useState("");
  const iosDevices = iosDeviceRows(user);
  if (!user.sessions.length && !iosDevices.length) return <Empty>Входов пока не было</Empty>;

  const kill = async (session) => {
    const live = session.isDevice !== false;
    const ok = await confirmDialog({
      title: live ? "Отключить устройство?" : "Завершить вход?",
      message: live
        ? "Туннель на этом устройстве упадёт сразу, приложение попросит войти заново."
        : "Кабинет в этом браузере попросит войти заново.",
      confirmText: live ? "Отключить" : "Завершить",
      danger: true,
    });
    if (!ok) return;
    setBusy(session.id);
    setWarning("");
    try {
      const result = await usersApi.killSession(user.id, session.id);

      if (result?.warnings?.length) {
        setWarning(`Токен погашен, но пир снят не везде: ${result.warnings.join("; ")}`);
      }
      const fresh = await usersApi.get(user.id);
      onChanged(fresh);
    } finally {
      setBusy(null);
    }
  };

  const dropKey = async (row) => {
    const ok = await confirmDialog({
      title: `Отключить ключ ${row.slot}?`,
      message:
        "Туннель на этом iPhone упадёт сразу. Ссылка останется за учёткой: человек сможет " +
        "включить её сам в кабинете, и после подключения ключ снова появится в устройствах.",
      confirmText: "Отключить",
      danger: true,
    });
    if (!ok) return;
    setBusy(`ios-${row.slot}`);
    setWarning("");
    try {
      onChanged(await usersApi.iosDisconnectKey(user.id, row.slot));
    } catch (err) {
      setWarning(err.message || "Не удалось отключить ключ");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card pad>
      {warning && (
        <div className="gd-cellsub" style={{ color: "var(--gd-neg)", marginBottom: 12 }}>
          {warning}
        </div>
      )}
      <div className="gd-rows">
        {user.sessions.map((session) => (
          <div key={session.id} className="gd-r">
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
                {session.deviceName || platformLabel(session.platform)}
                {session.appVersion && <span className="gd-chip">{session.appVersion}</span>}
                {session.isConnected && <Chip color="var(--gd-pos)">в VPN</Chip>}
                {session.isOnline && !session.isConnected && <Chip color="var(--gd-faint)">онлайн</Chip>}
                {session.isDevice === false && <Chip color="var(--gd-faint)">не устройство</Chip>}
                {session.revokedAt && <Chip color="var(--gd-faint)">завершена</Chip>}
              </div>
              <div className="gd-cellsub">
                вход {dateTime(session.createdAt)}
              </div>
            </div>
            <div className="r" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {ago(session.lastSeenAt)}
              {!session.revokedAt && (
                <Button size="sm" variant="danger" disabled={busy === session.id} onClick={() => kill(session)}>
                  {session.isDevice === false ? "Завершить" : "Отключить"}
                </Button>
              )}
            </div>
          </div>
        ))}

        {iosDevices.map((row) => (
          <div key={`ios-${row.slot}`} className="gd-r">
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
                iPhone · ключ {row.slot}
                <span className="gd-chip">AmneziaVPN</span>
                {row.connected && <Chip color="var(--gd-pos)">в VPN</Chip>}
              </div>
              <div className="gd-cellsub">
                ключ vpn:// вставлен в AmneziaVPN · выдан {date(row.createdAt)}
              </div>
            </div>
            <div className="r" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {ago(row.lastHandshakeAt)}
              <Button
                size="sm"
                variant="danger"
                disabled={busy === `ios-${row.slot}`}
                onClick={() => dropKey(row)}
              >
                Отключить
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function iosDeviceRows(user) {
  const bySlot = new Map();
  for (const key of user.iosKeys || []) {
    if (!key.isActive || !key.lastHandshakeAt) continue;
    const row = bySlot.get(key.slot) || {
      slot: key.slot,
      connected: false,
      lastHandshakeAt: key.lastHandshakeAt,
      createdAt: key.createdAt,
    };
    row.connected = row.connected || Boolean(key.isConnected);
    if (Date.parse(key.lastHandshakeAt) > Date.parse(row.lastHandshakeAt)) {
      row.lastHandshakeAt = key.lastHandshakeAt;
    }
    if (Date.parse(key.createdAt) < Date.parse(row.createdAt)) {
      row.createdAt = key.createdAt;
    }
    bySlot.set(key.slot, row);
  }
  return [...bySlot.values()].sort((a, b) => a.slot - b.slot);
}

function deviceLabel(user, deviceId) {
  if (!deviceId) return "общий ключ учётки";
  const session = user.sessions.find((s) => s.deviceId === deviceId);
  if (!session) return "устройство без входа";
  return session.deviceName || platformLabel(session.platform);
}

function Servers({ user }) {
  const live = user.keys.filter((k) => !k.revokedAt);
  if (!live.length) return <Empty>Ключей на серверах нет</Empty>;

  return (
    <Card pad>
      <Section
        title="Ключи на серверах"
        sub="По одному пиру на устройство — поэтому отключить можно одно, не трогая остальные"
      >
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
                  {key.address || "общий ключ"} · {key.serverName} ·{" "}
                  {deviceLabel(user, key.deviceId)}
                  {key.endpointPort ? ` · порт ${key.endpointPort}` : ""}
                </div>
              </div>
              <div className="r">
                {bytes(key.rxBytes + key.txBytes)}
                <div
                  className="gd-cellsub"
                  style={key.lastHandshakeAt ? undefined : { color: "var(--gd-neg)" }}
                >
                  {key.lastHandshakeAt ? ago(key.lastHandshakeAt) : "ни одного рукопожатия"}
                </div>
              </div>
            </div>
          ))}
        </div>
      </Section>
    </Card>
  );
}
