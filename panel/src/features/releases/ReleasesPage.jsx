import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { releasesApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { bytes, dateTime } from "../../lib/format";
import {
  Button,
  Card,
  Chip,
  Copyable,
  ErrorBox,
  Field,
  Loading,
  Modal,
  PageHead,
  Table,
  CellName,
  confirmDialog,
} from "../../ui";

const PLATFORM_LABELS = {
  windows: "Windows",
  android: "Android",
  macos: "macOS",
  linux: "Linux",
  ios: "iOS",
};

export function ReleasesPage() {
  const releases = useAsync(() => releasesApi.list(), []);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(null);

  const remove = async (row) => {
    const ok = await confirmDialog({
      title: `Убрать версию ${row.version} для ${PLATFORM_LABELS[row.platform] || row.platform}?`,
      message: "Приложения перестанут предлагать это обновление.",
      confirmText: "Убрать",
      danger: true,
    });
    if (!ok) return;
    setBusy(row.id);
    try {
      await releasesApi.remove(row.id);
      releases.reload(true);
    } finally {
      setBusy(null);
    }
  };

  const columns = [
    {
      key: "platform",
      title: "Платформа",
      render: (r) => (
        <CellName title={PLATFORM_LABELS[r.platform] || r.platform} sub={`версия ${r.version}`} />
      ),
    },
    {
      key: "url",
      title: "Ссылка на установщик",
      render: (r) => (
        <span style={{ fontSize: 12.5, color: "var(--gd-dim)", maxWidth: 320, display: "inline-block" }}>
          <Copyable text={r.url}>{r.url.length > 46 ? `${r.url.slice(0, 46)}…` : r.url}</Copyable>
        </span>
      ),
    },
    {
      key: "size",
      title: "Размер",
      num: true,
      render: (r) => (r.sizeBytes ? bytes(r.sizeBytes) : "—"),
    },
    {
      key: "flags",
      title: "",
      render: (r) => (
        <div style={{ display: "flex", gap: 6 }}>
          {r.isMandatory && <Chip color="var(--gd-neg)">обязательное</Chip>}
          {!r.isActive && <Chip color="var(--gd-faint)">выключено</Chip>}
        </div>
      ),
    },
    { key: "released", title: "Опубликовано", render: (r) => dateTime(r.releasedAt) },
    {
      key: "actions",
      title: "",
      render: (r) => (
        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
          <Button size="sm" onClick={() => setEditing(r)}>
            Изменить
          </Button>
          <Button size="sm" variant="danger" disabled={busy === r.id} onClick={() => remove(r)}>
            <Trash2 size={14} />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="gd-root">
      <PageHead title="Версии приложения" sub="Приложение само предложит обновиться">
        <Button variant="primary" onClick={() => setEditing({})}>
          <Plus size={16} />
          Опубликовать версию
        </Button>
      </PageHead>

      <ErrorBox error={releases.error} onRetry={releases.reload} />

      <Card className="gd-table-card">
        <Table
          columns={columns}
          rows={releases.data || []}
          keyOf={(r) => r.id}
          loading={releases.loading && !releases.data}
          empty="Версий пока нет — опубликуйте первую, и приложения увидят обновление"
        />
      </Card>

      {editing && (
        <ReleaseModal
          release={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            releases.reload(true);
          }}
        />
      )}
    </div>
  );
}

function ReleaseModal({ release, onClose, onSaved }) {
  const [form, setForm] = useState(() => ({
    platform: release?.platform || "windows",
    version: release?.version || "",
    url: release?.url || "",
    changelog: release?.changelog || "",
    sizeBytes: release?.sizeBytes ? String(release.sizeBytes) : "",
    sha256: release?.sha256 || "",
    isMandatory: release?.isMandatory ?? false,
    isActive: release?.isActive ?? true,
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (key) => (e) =>
    setForm((f) => ({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const invalid = !form.version.trim() || !form.url.trim();

  const save = async () => {
    if (invalid) return;
    setBusy(true);
    setError(null);
    try {
      await releasesApi.create({
        platform: form.platform,
        version: form.version.trim(),
        url: form.url.trim(),
        changelog: form.changelog.trim() || null,
        sizeBytes: form.sizeBytes ? Number(form.sizeBytes) : null,
        sha256: form.sha256.trim() || null,
        isMandatory: form.isMandatory,
        isActive: form.isActive,
      });
      onSaved();
    } catch (err) {
      setError(err.message || "Не удалось сохранить");
      setBusy(false);
    }
  };

  return (
    <Modal
      title={release ? `Версия ${release.version}` : "Новая версия"}
      wide
      onClose={onClose}
      footer={
        <>
          <Button size="sm" onClick={onClose}>
            Отмена
          </Button>
          <Button size="sm" variant="primary" disabled={busy || invalid} onClick={save}>
            {busy ? "Сохраняем…" : "Опубликовать"}
          </Button>
        </>
      }
    >
      <div className="gd-inset" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Платформа">
            <select className="gd-select" value={form.platform} onChange={set("platform")}>
              {Object.entries(PLATFORM_LABELS).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Версия" hint="Как в приложении: 2.2.0">
            <input className="gd-input" value={form.version} onChange={set("version")} placeholder="2.2.0" />
          </Field>
        </div>

        <Field label="Ссылка на установщик" hint="Прямая ссылка на .msi, .apk, .dmg или AppImage">
          <input
            className="gd-input"
            value={form.url}
            onChange={set("url")}
            placeholder="https://.../ProstoVPN-2.2.0.msi"
          />
        </Field>

        <Field label="Что нового" hint="Показывается в приложении на экране обновления">
          <textarea
            className="gd-textarea"
            style={{ minHeight: 100, fontFamily: "inherit", fontSize: 13 }}
            value={form.changelog}
            onChange={set("changelog")}
            placeholder="Вход по логину и паролю, список стран из аккаунта"
          />
        </Field>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 12 }}>
          <Field label="Размер, байт" hint="Необязательно">
            <input className="gd-input" inputMode="numeric" value={form.sizeBytes} onChange={set("sizeBytes")} />
          </Field>
          <Field label="SHA-256" hint="Необязательно — для проверки скачанного">
            <input className="gd-input" value={form.sha256} onChange={set("sha256")} />
          </Field>
        </div>

        <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={form.isActive} onChange={set("isActive")} style={{ width: 16, height: 16, accentColor: "var(--gd-gold)" }} />
            Предлагать обновление
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={form.isMandatory} onChange={set("isMandatory")} style={{ width: 16, height: 16, accentColor: "var(--gd-gold)" }} />
            Обязательное
          </label>
        </div>

        {error && <div className="gd-error">{error}</div>}
      </div>
    </Modal>
  );
}
