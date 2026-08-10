import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { plansApi } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { days, gb, money, trafficLimit } from "../../lib/format";
import {
  Button,
  Card,
  Chip,
  ErrorBox,
  Field,
  Loading,
  Modal,
  PageHead,
  Seg,
  confirmDialog,
} from "../../ui";

export function PlansPage() {
  const plans = useAsync(() => plansApi.list(), []);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(null);

  const remove = async (plan) => {
    const ok = await confirmDialog({
      title: `Удалить тариф «${plan.name}»?`,
      message: "Уже купленные подписки останутся — в них сохранена цена и срок на момент покупки.",
      confirmText: "Удалить",
      danger: true,
    });
    if (!ok) return;
    setBusy(plan.id);
    try {
      await plansApi.remove(plan.id);
      plans.reload(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="gd-root">
      <PageHead title="Тарифы" sub="Цена, срок и включённый трафик">
        <Button variant="primary" onClick={() => setEditing({})}>
          <Plus size={16} />
          Новый тариф
        </Button>
      </PageHead>

      <ErrorBox error={plans.error} onRetry={plans.reload} />

      {plans.loading && !plans.data ? (
        <Loading />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}>
          {(plans.data || []).map((plan) => (
            <Card key={plan.id} pad>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ fontSize: 15, fontWeight: 600 }}>{plan.name}</div>
                {!plan.isActive && <Chip color="var(--gd-faint)">выключен</Chip>}
              </div>
              <div className="gd-mono" style={{ fontSize: 12, color: "var(--gd-faint)", marginTop: 3 }}>
                {plan.code}
              </div>

              <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.025em", marginTop: 14 }} className="gd-num">
                {money(plan.price, plan.currency)}
              </div>
              <div style={{ fontSize: 12.5, color: "var(--gd-dim)", marginTop: 4 }}>
                за {days(plan.periodDays)} · {trafficLimit(plan.trafficLimitBytes)}
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                <Button size="sm" onClick={() => setEditing(plan)}>
                  Изменить
                </Button>
                <Button size="sm" variant="danger" disabled={busy === plan.id} onClick={() => remove(plan)}>
                  <Trash2 size={14} />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {editing && (
        <PlanModal
          plan={editing.id ? editing : null}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            plans.reload(true);
          }}
        />
      )}
    </div>
  );
}

function PlanModal({ plan, onClose, onSaved }) {
  const [form, setForm] = useState(() => ({
    code: plan?.code || "",
    name: plan?.name || "",
    price: plan ? String(plan.price) : "",
    periodDays: plan ? String(plan.periodDays) : "30",
    // Безлимит — это отсутствие лимита, отдельного флага в базе нет.
    unlimited: plan ? plan.trafficLimitBytes == null : false,
    limitGb: plan?.trafficLimitBytes != null ? String(Math.round(gb(plan.trafficLimitBytes))) : "100",
    isActive: plan ? plan.isActive : true,
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (key) => (e) =>
    setForm((f) => ({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const invalid = !form.code.trim() || !form.name.trim() || !Number(form.periodDays);

  const save = async () => {
    if (invalid) return;
    setBusy(true);
    setError(null);
    const payload = {
      code: form.code.trim(),
      name: form.name.trim(),
      price: Number(form.price.replace(",", ".")) || 0,
      periodDays: Number(form.periodDays),
      trafficLimitBytes: form.unlimited
        ? null
        : Math.round(Number(form.limitGb.replace(",", ".")) * 1024 ** 3),
      isActive: form.isActive,
    };
    try {
      if (plan) await plansApi.update(plan.id, payload);
      else await plansApi.create(payload);
      onSaved();
    } catch (err) {
      setError(err.message || "Не удалось сохранить");
      setBusy(false);
    }
  };

  return (
    <Modal
      title={plan ? `Тариф «${plan.name}»` : "Новый тариф"}
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
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Название">
            <input className="gd-input" value={form.name} onChange={set("name")} placeholder="Базовый" />
          </Field>
          <Field label="Код" hint="Латиница, без пробелов">
            <input className="gd-input" value={form.code} onChange={set("code")} placeholder="basic" />
          </Field>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Цена">
            <input className="gd-input" inputMode="decimal" value={form.price} onChange={set("price")} placeholder="199" />
          </Field>
          <Field label="Срок, дней">
            <input className="gd-input" inputMode="numeric" value={form.periodDays} onChange={set("periodDays")} />
          </Field>
        </div>

        <Field label="Трафик">
          <Seg
            gold
            full
            value={form.unlimited ? "unlimited" : "limited"}
            onChange={(id) => setForm((f) => ({ ...f, unlimited: id === "unlimited" }))}
            options={[
              { id: "limited", label: "Ограничен" },
              { id: "unlimited", label: "Безлимит" },
            ]}
          />
        </Field>

        {!form.unlimited && (
          <Field label="Сколько гигабайт">
            <input className="gd-input" inputMode="decimal" value={form.limitGb} onChange={set("limitGb")} />
          </Field>
        )}

        <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13, cursor: "pointer" }}>
          <input type="checkbox" checked={form.isActive} onChange={set("isActive")} style={{ width: 16, height: 16, accentColor: "var(--gd-gold)" }} />
          Доступен для новых подписок
        </label>

        {error && <div className="gd-error">{error}</div>}
      </div>
    </Modal>
  );
}
