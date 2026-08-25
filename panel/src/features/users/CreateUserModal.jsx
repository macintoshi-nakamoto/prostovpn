import { useState } from "react";
import { usersApi } from "../../lib/api";
import { days, money } from "../../lib/format";
import { Button, Field, Modal } from "../../ui";
import { CredentialsModal } from "./CredentialsModal";

export function CreateUserModal({ plans, onClose, onCreated }) {
  const activePlans = plans.filter((p) => p.isActive);
  const [form, setForm] = useState({
    name: "",
    contact: "",
    email: "",
    note: "",
    planCode: activePlans.find((p) => p.code === "basic")?.code || activePlans[0]?.code || "",
    login: "",
    manual: false,
    password: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [created, setCreated] = useState(null);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const plan = activePlans.find((p) => p.code === form.planCode);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await usersApi.create({
        name: form.name.trim() || null,
        contact: form.contact.trim() || null,
        email: form.email.trim() || null,
        note: form.note.trim() || null,
        planCode: form.planCode || null,
        login: form.manual && form.login.trim() ? form.login.trim() : null,
        password: form.manual && form.password ? form.password : null,
      });

      setCreated(result);
    } catch (err) {
      setError(err.message || "Не удалось создать");
      setBusy(false);
    }
  };

  if (created) {
    return (
      <CredentialsModal
        login={created.user.login}
        password={created.password}
        publicId={created.user.publicId}
        onClose={() => onCreated(created)}
      />
    );
  }

  return (
    <Modal
      title="Новый пользователь"
      wide
      onClose={onClose}
      footer={
        <>
          <Button size="sm" onClick={onClose}>
            Отмена
          </Button>
          <Button size="sm" variant="primary" disabled={busy} onClick={submit}>
            {busy ? "Создаём…" : "Создать и выдать доступы"}
          </Button>
        </>
      }
    >
      <div className="gd-inset" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Имя">
            <input className="gd-input" value={form.name} onChange={set("name")} placeholder="Иван Морозов" />
          </Field>
          <Field label="Контакт">
            <input className="gd-input" value={form.contact} onChange={set("contact")} placeholder="@ivan" />
          </Field>
        </div>

        <Field
          label="Почта"
          hint="По ней повторная покупка на сайте продлит эту учётку, а не заведёт вторую"
        >
          <input
            className="gd-input"
            type="email"
            value={form.email}
            onChange={set("email")}
            placeholder="ivan@example.com"
          />
        </Field>

        <Field label="Тариф">
          <select className="gd-select" value={form.planCode} onChange={set("planCode")}>
            {activePlans.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name} — {money(p.price, p.currency)} за {days(p.periodDays)}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Заметка">
          <input className="gd-input" value={form.note} onChange={set("note")} placeholder="Откуда пришёл, договорённости" />
        </Field>

        <label style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={form.manual}
            onChange={(e) => setForm((f) => ({ ...f, manual: e.target.checked }))}
            style={{ width: 16, height: 16, accentColor: "var(--gd-gold)" }}
          />
          Задать логин и пароль вручную
        </label>

        {form.manual && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Логин" hint="Латиница, цифры, дефис">
              <input className="gd-input" value={form.login} onChange={set("login")} placeholder="ivan-morozov" />
            </Field>
            <Field label="Пароль" hint="Пусто — сгенерируем">
              <input className="gd-input" value={form.password} onChange={set("password")} placeholder="••••••••" />
            </Field>
          </div>
        )}

        <div style={{ fontSize: 12.5, color: "var(--gd-faint)", lineHeight: 1.5 }}>
          После создания клиенту сразу выдаются ключи на всех включённых серверах
          {plan ? ` и открывается доступ на ${days(plan.periodDays)}` : ""}.
        </div>

        {error && <div className="gd-error">{error}</div>}
      </div>
    </Modal>
  );
}
