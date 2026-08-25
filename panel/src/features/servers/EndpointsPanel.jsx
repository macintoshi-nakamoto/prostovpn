import { useState } from "react";
import { Plus, RefreshCw, Server as ServerIcon, Shield } from "lucide-react";
import { endpointsApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { Button, Chip, Empty, ErrorBox, Loading, Modal, confirmDialog } from "../../ui";

const STATE_LABEL = {
  draft: "черновик",
  active: "принимает",
  draining: "слив",
  retired: "выведена",
};

const STATE_COLOR = {
  draft: "var(--gd-muted)",
  active: "var(--gd-ok)",
  draining: "var(--gd-warn)",
  retired: "var(--gd-muted)",
};

const OBF_ORDER = [
  ["jc", "Jc"],
  ["jmin", "Jmin"],
  ["jmax", "Jmax"],
  ["s1", "S1"],
  ["s2", "S2"],
  ["h1", "H1"],
  ["h2", "H2"],
  ["h3", "H3"],
  ["h4", "H4"],
];

function Obfuscation({ values }) {
  if (!values) return null;

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px", fontSize: 12 }}>
      {OBF_ORDER.map(([key, label]) => (
        <span key={key} style={{ color: "var(--gd-muted)" }}>
          {label} <span className="gd-mono" style={{ color: "var(--gd-fg)" }}>{values[key]}</span>
        </span>
      ))}
    </div>
  );
}

function VlessModal({ serverId, onClose, onCreated }) {
  const [form, setForm] = useState({ port: 2053, names: "www.google.com" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await endpointsApi.createVless({
        server_id: serverId,
        listen_port: Number(form.port),
        server_names: form.names.split(",").map((s) => s.trim()).filter(Boolean),
      });
      onCreated();
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Второй протокол (VLESS + Reality)"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>
            {busy ? "…" : "Завести"}
          </Button>
        </>
      }
    >
      <ErrorBox error={error} />
      <label className="gd-field">
        <span>Порт</span>
        <input
          type="number"
          value={form.port}
          onChange={(e) => setForm({ ...form, port: e.target.value })}
        />
      </label>
      <label className="gd-field">
        <span>Донорские домены</span>
        <input
          value={form.names}
          onChange={(e) => setForm({ ...form, names: e.target.value })}
          placeholder="www.google.com"
        />
      </label>
      <p style={{ fontSize: 12.5, color: "var(--gd-muted)", marginTop: 8 }}>
        Соединение будет выглядеть как обычный HTTPS к этому сайту. Домен должен
        поддерживать TLS 1.3 и быстро отвечать с узла. Менять список у живой
        точки входа нельзя — заведите вторую, а первую переведите в слив.
      </p>
    </Modal>
  );
}

export function EndpointsPanel({ serverId }) {
  const list = useAsync(() => endpointsApi.list(serverId), [serverId]);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);

  const run = async (tag, fn) => {
    setBusy(tag);
    setError(null);
    try {
      await fn();
      await list.reload(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const drain = async (row) => {
    const ok = await confirmDialog({
      title: `Перевести ${row.handle} в слив?`,
      message:
        "Новых подключений сюда больше не будет. Те, кто уже здесь, продолжат " +
        "работать и переедут сами при следующем перевыпуске ключа.",
      confirmText: "Перевести",
    });
    if (ok) run(`${row.id}:state`, () => endpointsApi.setState(row.id, "draining"));
  };

  const retire = async (row) => {
    const ok = await confirmDialog({
      title: `Вывести ${row.handle} из обращения?`,
      message:
        row.kind === "vless"
          ? "Все выданные на ней доступы будут отозваны, сохранённые ссылки перестанут работать."
          : "Интерфейс можно вывести, только когда на нём не осталось доступов.",
      confirmText: "Вывести",
      danger: true,
    });
    if (ok) run(`${row.id}:state`, () => endpointsApi.setState(row.id, "retired"));
  };

  if (list.loading) return <Loading text="Читаем точки входа" />;

  const rows = list.data || [];

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <b style={{ fontSize: 13 }}>Точки входа</b>
        <span style={{ fontSize: 12, color: "var(--gd-muted)" }}>
          у каждой свой набор обфускации — так отпечаток дробится
        </span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <Button
            size="sm"
            disabled={busy === "new"}
            onClick={() => run("new", () => endpointsApi.create({ server_id: serverId }))}
          >
            <Plus size={14} /> {busy === "new" ? "…" : "AmneziaWG"}
          </Button>
          <Button size="sm" onClick={() => setModal("vless")}>
            <Shield size={14} /> VLESS
          </Button>
        </span>
      </div>

      <ErrorBox error={error || list.error} onRetry={list.error ? () => list.reload() : undefined} />

      {rows.length === 0 ? (
        <Empty>
          Точек входа нет — узел работает по-старому, одним интерфейсом. Добавьте
          AmneziaWG: новые подключения распределятся между интерфейсами, и у
          каждого будет свой набор параметров.
        </Empty>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {rows.map((row) => (
            <div
              key={row.id}
              style={{
                border: "1px solid var(--gd-line)",
                borderRadius: 10,
                padding: "10px 12px",
                display: "grid",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600 }}>
                  {row.kind === "vless" ? <Shield size={14} /> : <ServerIcon size={14} />}
                  {row.handle}
                </span>
                <Chip color={STATE_COLOR[row.state]}>{STATE_LABEL[row.state] || row.state}</Chip>
                <span style={{ fontSize: 12, color: "var(--gd-muted)" }}>
                  порт {row.listen_port}
                  {row.subnet ? ` · ${row.subnet}` : ""}
                  {` · ${row.used}${row.capacity ? ` / ${row.capacity}` : ""} доступов`}
                </span>
              </div>

              <Obfuscation values={row.obfuscation} />

              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {row.state === "draft" && row.kind === "awg" && (
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={busy === `${row.id}:apply`}
                    onClick={() => run(`${row.id}:apply`, () => endpointsApi.apply(row.id))}
                  >
                    {busy === `${row.id}:apply` ? "…" : "Поднять на узле"}
                  </Button>
                )}
                {row.kind === "vless" && row.state !== "retired" && (
                  <Button
                    size="sm"
                    disabled={busy === `${row.id}:sync`}
                    onClick={() => run(`${row.id}:sync`, () => endpointsApi.sync(row.id))}
                  >
                    <RefreshCw size={14} />
                    {busy === `${row.id}:sync` ? "…" : "Записать на узел"}
                  </Button>
                )}
                {row.state === "active" && (
                  <Button size="sm" onClick={() => drain(row)}>
                    В слив
                  </Button>
                )}
                {row.state === "draining" && (
                  <>
                    <Button
                      size="sm"
                      disabled={busy === `${row.id}:state`}
                      onClick={() =>
                        run(`${row.id}:state`, () => endpointsApi.setState(row.id, "active"))
                      }
                    >
                      Вернуть в работу
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => retire(row)}>
                      Вывести
                    </Button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {modal === "vless" && (
        <VlessModal
          serverId={serverId}
          onClose={() => setModal(null)}
          onCreated={() => list.reload(true)}
        />
      )}
    </div>
  );
}
