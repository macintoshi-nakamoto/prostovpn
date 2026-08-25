import { useState } from "react";
import { RotateCcw, Trash2, Upload } from "lucide-react";
import { tunnelApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { bytes, dateTime } from "../../lib/format";
import {
  Button,
  Card,
  CellName,
  Chip,
  Copyable,
  ErrorBox,
  Field,
  Modal,
  PageHead,
  Table,
  confirmDialog,
} from "../../ui";

export function TunnelFilePage() {
  const versions = useAsync(() => tunnelApi.list(), []);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(null);
  const [viewing, setViewing] = useState(null);

  const rows = versions.data || [];
  const active = rows.find((row) => row.isActive);

  const activate = async (row) => {
    const ok = await confirmDialog({
      title: `Вернуть версию «${row.version || row.filename}»?`,
      message:
        "Она станет текущей: кабинет, бот и приложения начнут отдавать её " +
        "при следующем обращении. Нынешняя версия останется в истории.",
      confirmText: "Вернуть",
    });
    if (!ok) return;
    setBusy(row.id);
    try {
      await tunnelApi.activate(row.id);
      versions.reload(true);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (row) => {
    const ok = await confirmDialog({
      title: `Удалить версию «${row.version || row.filename}»?`,
      message: "Из истории она пропадёт совсем, откатиться на неё будет нельзя.",
      confirmText: "Удалить",
      danger: true,
    });
    if (!ok) return;
    setBusy(row.id);
    try {
      await tunnelApi.remove(row.id);
      versions.reload(true);
    } finally {
      setBusy(null);
    }
  };

  const view = async (row) => {
    setBusy(row.id);
    try {
      setViewing(await tunnelApi.get(row.id));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="gd-root">
      <PageHead
        title="Файл обхода"
        sub="Список российских сервисов, которые идут мимо VPN"
      >
        <Button variant="primary" onClick={() => setUploading(true)}>
          <Upload size={15} />
          Загрузить версию
        </Button>
      </PageHead>

      <ErrorBox error={versions.error} onRetry={versions.reload} />

      {active && (
        <Card pad style={{ marginBottom: 14 }}>
          <div className="gd-sec-title">Сейчас отдаётся</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 18, marginTop: 8 }}>
            <div>
              <div className="gd-tile-l">Файл</div>
              <div className="gd-mono">{active.filename}</div>
            </div>
            <div>
              <div className="gd-tile-l">Версия</div>
              <div>{active.version || "—"}</div>
            </div>
            <div>
              <div className="gd-tile-l">Размер</div>
              <div>{bytes(active.sizeBytes)}</div>
            </div>
            <div>
              <div className="gd-tile-l">Обновлён</div>
              <div>{dateTime(active.updatedAt)}</div>
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="gd-tile-l">sha256</div>
              <div className="gd-cellsub" style={{ maxWidth: 260 }}>
                <Copyable text={active.sha256} />
              </div>
            </div>
          </div>
        </Card>
      )}

      <Card className="gd-table-card">
        <Table
          columns={[
            {
              key: "file",
              title: "Файл",
              render: (r) => <CellName title={r.filename} sub={r.note || "без заметки"} />,
            },
            { key: "version", title: "Версия", render: (r) => r.version || "—" },
            { key: "size", title: "Размер", num: true, render: (r) => bytes(r.sizeBytes) },
            { key: "updated", title: "Обновлён", render: (r) => dateTime(r.updatedAt) },
            {
              key: "state",
              title: "",
              render: (r) =>
                r.isActive ? (
                  <Chip color="var(--gd-pos)">текущая</Chip>
                ) : (
                  <Button size="sm" disabled={busy === r.id} onClick={() => activate(r)}>
                    <RotateCcw size={13} />
                    Вернуть
                  </Button>
                ),
            },
            {
              key: "actions",
              title: "",
              render: (r) => (
                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                  <Button size="sm" disabled={busy === r.id} onClick={() => view(r)}>
                    Показать
                  </Button>
                  {!r.isActive && (
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={busy === r.id}
                      onClick={() => remove(r)}
                    >
                      <Trash2 size={14} />
                    </Button>
                  )}
                </div>
              ),
            },
          ]}
          rows={rows}
          keyOf={(r) => r.id}
          loading={versions.loading && !versions.data}
          empty="Файла ещё нет. Загрузите JSON со списком подсетей — он сразу станет текущим, и кабинет с ботом начнут его отдавать."
        />
      </Card>

      {uploading && (
        <UploadModal
          onClose={() => setUploading(false)}
          onSaved={() => {
            setUploading(false);
            versions.reload(true);
          }}
        />
      )}

      {viewing && <ContentModal entry={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

function UploadModal({ onClose, onSaved }) {
  const [content, setContent] = useState("");
  const [filename, setFilename] = useState("");
  const [version, setVersion] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const pick = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setFilename(file.name);
    setContent(await file.text());
    setError(null);
  };

  const save = async () => {
    if (!content.trim()) {
      setError("Файл пустой — нечего сохранять");
      return;
    }

    try {
      JSON.parse(content);
    } catch (err) {
      setError(`Это не JSON: ${err.message}`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await tunnelApi.upload({
        content,
        filename: filename || null,
        version: version || null,
        note: note || null,
      });
      onSaved();
    } catch (err) {
      setError(err.message || "Не удалось сохранить");
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Новая версия файла обхода"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={save}>
            {busy ? "Сохраняем…" : "Сохранить и включить"}
          </Button>
        </>
      }
    >
      {error && <div className="gd-error" style={{ marginBottom: 12 }}>{error}</div>}

      <Field label="Выбрать файл" hint="JSON со списком подсетей">
        <input className="gd-input" type="file" accept=".json,application/json" onChange={pick} />
      </Field>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="Имя файла" hint="Под ним его скачает человек">
          <input
            className="gd-input"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="prostovpn-ru-direct.json"
          />
        </Field>
        <Field label="Версия" hint="Необязательно">
          <input
            className="gd-input"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="2026-08-19"
          />
        </Field>
      </div>

      <Field label="Заметка" hint="Что поменялось — видно в истории">
        <input
          className="gd-input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Добавлены домены Сбербанка"
        />
      </Field>

      <Field label="Содержимое" hint="Можно вставить или поправить прямо здесь">
        <textarea
          className="gd-input"
          rows={10}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder='{"routes": ["5.61.16.0/21", "..."]}'
          style={{ fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 12.5 }}
        />
      </Field>
    </Modal>
  );
}

function ContentModal({ entry, onClose }) {
  return (
    <Modal
      title={`${entry.filename}${entry.version ? ` · ${entry.version}` : ""}`}
      onClose={onClose}
      footer={<Button onClick={onClose}>Закрыть</Button>}
    >
      <div className="gd-cellsub" style={{ marginBottom: 10 }}>
        {bytes(entry.sizeBytes)} · обновлён {dateTime(entry.updatedAt)}
        {entry.note ? ` · ${entry.note}` : ""}
      </div>
      <textarea
        className="gd-input"
        rows={16}
        readOnly
        value={entry.content || ""}
        style={{ fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 12.5 }}
      />
    </Modal>
  );
}
