import { useState } from "react";
import { Check, ChevronDown, ChevronRight, Plus, RefreshCw, Stethoscope, Trash2, X } from "lucide-react";
import { serversApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { ago, bytes, flag, num, plural } from "../../lib/format";
import {
  Button,
  Card,
  Chip,
  Dot,
  ErrorBox,
  KV,
  Loading,
  Modal,
  PageHead,
  StatusDot,
  Tile,
  Toggle,
  confirmDialog,
} from "../../ui";
import { ServerModal } from "./ServerModal";

/**
 * Состояние узла одной строкой.
 *
 * «Включён» и «работает» — разные вещи, и раньше панель показывала только
 * первое. Отсюда и брался вопрос «почему клиент не может подключиться, у
 * меня же всё зелёное»: включить можно и узел с адресом, которого не
 * существует.
 */
function Health({ server }) {
  const state = healthState(server);
  return (
    <div
      style={{
        marginTop: 14,
        padding: "11px 14px",
        borderRadius: 8,
        background: `color-mix(in srgb, ${state.color} 12%, transparent)`,
        border: `1px solid color-mix(in srgb, ${state.color} 35%, transparent)`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
        <Dot color={state.color} glow={state.ok} />
        <span style={{ fontSize: 13.5, fontWeight: 600, color: state.color }}>{state.label}</span>
        {server.healthCheckedAt && (
          <span className="gd-tile-l" style={{ marginLeft: "auto" }}>
            проверено {ago(server.healthCheckedAt)}
          </span>
        )}
      </div>
      {server.healthSummary && (
        <div style={{ fontSize: 12.5, color: "var(--gd-dim)", marginTop: 6, lineHeight: 1.5 }}>
          {server.healthSummary}
        </div>
      )}
    </div>
  );
}

function healthState(server) {
  if (!server.isActive) return { ok: false, color: "var(--gd-faint)", label: "Выключен" };
  if (server.healthOk === true) return { ok: true, color: "var(--gd-pos)", label: "Рабочий" };
  if (server.healthOk === false) return { ok: false, color: "var(--gd-neg)", label: "Не работает" };
  if (!server.canServe)
    return { ok: false, color: "var(--gd-warn)", label: "Не сможет выдать конфиг" };
  return { ok: false, color: "var(--gd-info)", label: "Не проверялся" };
}

/**
 * Открыт ли блок «Данные сервера».
 *
 * Помним выбор между перезагрузками и общим на все карточки: развернув его
 * один раз, администратор ждёт его развёрнутым и завтра, а свернув —
 * свёрнутым на всех узлах, а не только на том, где нажал.
 */
const FACTS_OPEN_KEY = "panel.serverFacts.open";

function factsOpenDefault() {
  return localStorage.getItem(FACTS_OPEN_KEY) === "1";
}

/**
 * Что за машина: железо, система, состояние туннеля.
 *
 * Свёрнут по умолчанию: полтора десятка строк на каждой карточке узла
 * отодвигали вниз всё остальное, а нужны они редко — когда с узлом что-то
 * не так. Свёрнутая строка оставляет главное: систему и аптайм.
 */
function Facts({ facts }) {
  const [open, setOpen] = useState(factsOpenDefault);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    localStorage.setItem(FACTS_OPEN_KEY, next ? "1" : "0");
  };

  if (!facts) return null;

  const mem =
    facts.memTotalBytes && facts.memAvailableBytes
      ? `${bytes(facts.memTotalBytes - facts.memAvailableBytes)} из ${bytes(facts.memTotalBytes)}`
      : facts.memTotalBytes
        ? bytes(facts.memTotalBytes)
        : null;

  const disk =
    facts.diskTotalBytes && facts.diskUsedBytes
      ? `${bytes(facts.diskUsedBytes)} из ${bytes(facts.diskTotalBytes)}`
      : null;

  const cpu = [facts.cpuCount && `${facts.cpuCount} ядер`, facts.cpuModel].filter(Boolean).join(" · ");

  const rows = [
    ["Система", [facts.os, facts.kernel].filter(Boolean).join(" · ")],
    ["Процессор", cpu],
    ["Память", mem],
    ["Диск", disk],
    ["Аптайм", uptime(facts.uptimeSeconds)],
    ["Средняя нагрузка", facts.load],
    ["Внешний адрес", facts.publicIp],
    ["AmneziaWG", facts.awgVersion],
    [
      "Интерфейс awg0",
      facts.interfaceUp === true
        ? `поднят${facts.interfaceAddress ? ` · ${facts.interfaceAddress}` : ""}${
            facts.listenPort ? ` · порт ${facts.listenPort}` : ""
          }`
        : facts.interfaceUp === false
          ? "не поднят"
          : null,
    ],
    ["Пиров на узле", facts.peers != null ? String(facts.peers) : null],
    [
      "Трафик интерфейса",
      facts.interfaceRxBytes != null
        ? `${bytes(facts.interfaceRxBytes)} принято · ${bytes(facts.interfaceTxBytes || 0)} отдано`
        : null,
    ],
  ].filter(([, value]) => value);

  if (!rows.length) return null;

  // Что видно в свёрнутом виде — самое частое «а что там вообще за машина».
  const short = [facts.os, uptime(facts.uptimeSeconds)].filter(Boolean).join(" · ");

  return (
    <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--gd-tile)" }}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: 0,
          background: "none",
          border: 0,
          color: "inherit",
          font: "inherit",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span style={{ display: "flex", color: "var(--gd-dim)" }}>
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </span>
        <span className="gd-sec-title" style={{ margin: 0 }}>
          Данные сервера
        </span>
        {!open && short && (
          <span
            className="gd-tile-l"
            style={{ marginTop: 0, marginLeft: "auto", maxWidth: "60%" }}
          >
            {short}
          </span>
        )}
      </button>

      {open && (
        <div style={{ marginTop: 8 }}>
          {rows.map(([label, value]) => (
            <KV key={label} k={label}>
              {value}
            </KV>
          ))}

          {facts.ipForward === false && (
            <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--gd-neg)", lineHeight: 1.5 }}>
              Пересылка пакетов выключена: туннель поднимется, но интернет через него не пойдёт.
              На сервере: <span className="gd-mono">sysctl -w net.ipv4.ip_forward=1</span>
            </div>
          )}
          {facts.awgService && facts.awgService !== "active" && (
            <div style={{ marginTop: 8, fontSize: 12.5, color: "var(--gd-warn)" }}>
              Служба awg-quick@awg0: {facts.awgService}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function uptime(seconds) {
  if (!seconds) return null;
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  if (days) return `${days} ${plural(days, "день", "дня", "дней")} ${hours} ч`;
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours} ч ${minutes} мин` : `${minutes} мин`;
}

export function ServersPage() {
  const servers = useAsync(() => serversApi.list(), []);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const [report, setReport] = useState(null);

  const rows = servers.data || [];
  const active = rows.filter((s) => s.isActive).length;
  // «Рабочий» — это узел, включённый и способный выдать конфиг, а по
  // последней проверке ещё и живой. Именно это число отвечает на вопрос
  // «смогут ли клиенты подключиться», а не количество включённых.
  const usable = rows.filter((s) => s.isActive && s.canServe && s.healthOk !== false).length;
  const keys = rows.reduce((sum, s) => sum + s.keysActive, 0);

  const toggle = async (server) => {
    setBusy(server.id);
    try {
      await serversApi.toggle(server.id);
      servers.reload(true);
    } finally {
      setBusy(null);
    }
  };

  /**
   * Проверка узла по-настоящему: адрес, порт, SSH, поднятый интерфейс.
   *
   * Появилась после случая, когда все узлы в базе были демонстрационными —
   * с адресами из документационных диапазонов, которые никуда не ведут.
   * Панель показывала их зелёными: «включён» она умела, «работает» — нет.
   */
  const check = async (server) => {
    setBusy(server.id);
    setNotice(null);
    setReport(null);
    try {
      setReport(await serversApi.check(server.id));
      servers.reload(true);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(null);
    }
  };

  const sync = async (server) => {
    setBusy(server.id);
    setNotice(null);
    try {
      const result = await serversApi.syncTraffic(server.id);
      setNotice(
        result.error
          ? `${server.name}: ${result.error}`
          : result.skipped
            ? `${server.name}: ${result.skipped}`
            : `${server.name}: обновлено пиров — ${result.peers}`,
      );
      servers.reload(true);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (server) => {
    const ok = await confirmDialog({
      title: `Удалить сервер «${server.name}»?`,
      message: "Вместе с ним удалятся все выданные на нём ключи. Пиры на самом сервере останутся.",
      confirmText: "Удалить",
      danger: true,
    });
    if (!ok) return;
    setBusy(server.id);
    try {
      await serversApi.remove(server.id);
      servers.reload(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="gd-root">
      <PageHead title="Серверы" sub="Точки подключения и раздача ключей">
        <Button onClick={() => servers.reload()}>
          <RefreshCw size={15} />
        </Button>
        <Button variant="primary" onClick={() => setEditing({})}>
          <Plus size={16} />
          Добавить сервер
        </Button>
      </PageHead>

      <div className="gd-tiles" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))", marginBottom: 16 }}>
        <Tile label="Всего серверов" value={num(rows.length)} />
        <Tile label="Включено" value={num(active)} dot="var(--gd-pos)" />
        <Tile
          label="Рабочих"
          value={num(usable)}
          dot={usable ? "var(--gd-pos)" : "var(--gd-neg)"}
          sub={usable ? undefined : "клиенты не смогут подключиться"}
        />
        <Tile label="Выдано ключей" value={num(keys)} />
      </div>

      {notice && (
        <div className="gd-error" style={{ marginBottom: 12, background: "var(--gd-card)", color: "var(--gd-dim)" }}>
          {notice}
        </div>
      )}
      <ErrorBox error={servers.error} onRetry={servers.reload} />

      {servers.loading && !servers.data ? (
        <Loading />
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {rows.map((server) => (
            <Card key={server.id} pad>
              <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                <span style={{ fontSize: 26 }}>{flag(server.countryCode)}</span>

                <div style={{ minWidth: 0, flex: "1 1 200px" }}>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>
                    {server.country || server.name}
                    {server.city ? `, ${server.city}` : ""}
                  </div>
                  <div className="gd-cellsub gd-mono">
                    {server.name} · {server.host}:{server.port}
                  </div>
                </div>

                <Chip color={server.provisioning === "ssh" ? "var(--gd-gold)" : "var(--gd-info)"}>
                  {server.provisioning === "ssh" ? "своя генерация" : "общий ключ"}
                </Chip>

                <StatusDot
                  color={server.isActive ? "var(--gd-pos)" : "var(--gd-faint)"}
                  label={server.isActive ? "Включён" : "Выключен"}
                />

                <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <Toggle on={server.isActive} disabled={busy === server.id} onChange={() => toggle(server)} />
                  <Button size="sm" onClick={() => setEditing(server)}>
                    Настроить
                  </Button>
                  <Button size="sm" disabled={busy === server.id} onClick={() => check(server)}>
                    <Stethoscope size={14} />
                    Проверить
                  </Button>
                  {server.provisioning === "ssh" && (
                    <Button size="sm" disabled={busy === server.id} onClick={() => sync(server)}>
                      Снять трафик
                    </Button>
                  )}
                  <Button size="sm" variant="danger" disabled={busy === server.id} onClick={() => remove(server)}>
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>

              <Health server={server} />

              <div style={{ marginTop: 12 }}>
                <KV k="Адрес">
                  <span className="gd-mono">
                    {server.host}:{server.port}
                  </span>
                </KV>
                <KV k="Ключей выдано">
                  {server.keysActive} из {server.keysTotal}
                </KV>
                <KV k="Шаблон конфига">
                  {server.hasTemplate ? "задан" : <span style={{ color: "var(--gd-warn)" }}>не задан</span>}
                </KV>
                <KV k="Счётчики трафика">
                  {server.trafficError ? (
                    <span style={{ color: "var(--gd-neg)" }}>{server.trafficError}</span>
                  ) : server.trafficSyncedAt ? (
                    ago(server.trafficSyncedAt)
                  ) : (
                    "не снимались"
                  )}
                </KV>
              </div>

              <Facts facts={server.facts} />
            </Card>
          ))}

          {!rows.length && (
            <Card pad>
              <div className="gd-empty">
                Серверов пока нет. Добавьте первый — ключи разойдутся клиентам сами.
              </div>
            </Card>
          )}
        </div>
      )}

      {report && (
        <Modal
          title={`Проверка · ${report.serverName}`}
          onClose={() => setReport(null)}
          footer={
            <Button size="sm" variant="primary" onClick={() => setReport(null)}>
              Понятно
            </Button>
          }
        >
          <div className="gd-inset">
            <div
              style={{
                fontSize: 14,
                lineHeight: 1.55,
                color: report.usable ? "var(--gd-pos)" : "var(--gd-neg)",
                marginBottom: 18,
              }}
            >
              {report.summary}
            </div>

            {report.checks.map((item) => (
              <div key={item.name} style={{ display: "flex", gap: 12, padding: "10px 0", borderTop: "1px solid var(--gd-tile)" }}>
                <span style={{ flex: "none", marginTop: 2, color: item.ok ? "var(--gd-pos)" : "var(--gd-neg)" }}>
                  {item.ok ? <Check size={16} /> : <X size={16} />}
                </span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>{item.name}</div>
                  {item.detail && (
                    <div style={{ fontSize: 12.5, color: "var(--gd-dim)", lineHeight: 1.5, whiteSpace: "normal" }}>
                      {item.detail}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Modal>
      )}

      {editing && (
        <ServerModal
          server={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={(result) => {
            setEditing(null);
            servers.reload(true);
            if (result?.issued != null) {
              setNotice(
                `Сервер добавлен. Ключей выдано: ${result.issued}` +
                  (result.warnings?.length ? `. Предупреждения: ${result.warnings.join("; ")}` : ""),
              );
            }
          }}
        />
      )}
    </div>
  );
}
