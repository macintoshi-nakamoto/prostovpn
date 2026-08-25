import { useState } from "react";
import { usersApi } from "../../lib/api";
import { bytes, gb } from "../../lib/format";
import { Button, Field, Modal, Seg } from "../../ui";

const PRESETS = [50, 100, 250, 500, 1000];

export function TrafficLimitModal({ user, onClose, onSaved }) {
  const [mode, setMode] = useState(user.trafficLimitBytes == null ? "unlimited" : "limited");
  const [value, setValue] = useState(
    user.trafficLimitBytes == null ? "100" : String(Math.round(gb(user.trafficLimitBytes))),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const amount = Number(value.replace(",", "."));
  const invalid = mode === "limited" && (!isFinite(amount) || amount <= 0);

  const save = async () => {
    if (invalid) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await usersApi.setTrafficLimit(user.id, {
        unlimited: mode === "unlimited",
        limitGb: mode === "unlimited" ? null : amount,
      });
      onSaved(updated);
    } catch (err) {
      setError(err.message || "Не удалось сохранить");
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Лимит трафика"
      onClose={onClose}
      footer={
        <>
          <Button size="sm" onClick={onClose}>
            Отмена
          </Button>
          <Button size="sm" variant="primary" disabled={busy || invalid} onClick={save}>
            Сохранить
          </Button>
        </>
      }
    >
      <div className="gd-inset" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Seg
          gold
          full
          value={mode}
          onChange={setMode}
          options={[
            { id: "limited", label: "Ограничить" },
            { id: "unlimited", label: "Безлимит" },
          ]}
        />

        {mode === "limited" ? (
          <>
            <Field label="Сколько гигабайт">
              <input
                className="gd-input"
                inputMode="decimal"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="100"
              />
            </Field>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {PRESETS.map((preset) => (
                <Button key={preset} size="sm" onClick={() => setValue(String(preset))}>
                  {preset} ГБ
                </Button>
              ))}
            </div>
          </>
        ) : (
          <div style={{ fontSize: 13, color: "var(--gd-dim)", lineHeight: 1.5 }}>
            Ограничения не будет — сколько бы человек ни скачал, доступ останется.
          </div>
        )}

        <div style={{ fontSize: 12.5, color: "var(--gd-faint)" }}>
          Израсходовано сейчас: {bytes(user.trafficUsedBytes)}. Личный лимит важнее тарифного.
        </div>

        {error && <div className="gd-error">{error}</div>}
      </div>
    </Modal>
  );
}
