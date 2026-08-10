import { useState } from "react";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { serversApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { ago, flag, num } from "../../lib/format";
import {
  Button,
  Card,
  Chip,
  ErrorBox,
  KV,
  Loading,
  PageHead,
  StatusDot,
  Tile,
  Toggle,
  confirmDialog,
} from "../../ui";
import { ServerModal } from "./ServerModal";

export function ServersPage() {
  const servers = useAsync(() => serversApi.list(), []);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);

  const rows = servers.data || [];
  const active = rows.filter((s) => s.isActive).length;
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

      <div className="gd-tiles" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))", marginBottom: 16 }}>
        <Tile label="Всего серверов" value={num(rows.length)} />
        <Tile label="Включено" value={num(active)} dot="var(--gd-pos)" />
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

              <div style={{ marginTop: 12 }}>
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
