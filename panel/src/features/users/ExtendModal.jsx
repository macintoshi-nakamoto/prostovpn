import { useState } from "react";
import { usersApi } from "../../lib/api";
import { date, days, money } from "../../lib/format";
import { Button, Field, Modal } from "../../ui";

/**
 * Продление подписки.
 *
 * Продление и оплата — одно действие: если разнести их по разным экранам,
 * доступ и деньги рано или поздно разъедутся.
 */
export function ExtendModal({ user, plans, onClose, onSaved }) {
  const activePlans = plans.filter((p) => p.isActive);
  const [planCode, setPlanCode] = useState(user.plan || activePlans[0]?.code || "");
  const [customDays, setCustomDays] = useState("");
  const [registerPayment, setRegisterPayment] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const plan = activePlans.find((p) => p.code === planCode);
  const period = customDays ? Number(customDays) : plan?.periodDays;
  const invalid = !plan || !period || period <= 0;

  const save = async () => {
    if (invalid) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await usersApi.extend(user.id, {
        planCode,
        days: customDays ? Number(customDays) : undefined,
        registerPayment,
      });
      onSaved(updated);
    } catch (err) {
      setError(err.message || "Не удалось продлить");
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Продлить подписку"
      onClose={onClose}
      footer={
        <>
          <Button size="sm" onClick={onClose}>
            Отмена
          </Button>
          <Button size="sm" variant="primary" disabled={busy || invalid} onClick={save}>
            Продлить
          </Button>
        </>
      }
    >
      <div className="gd-inset" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Field label="Тариф">
          <select className="gd-select" value={planCode} onChange={(e) => setPlanCode(e.target.value)}>
            {activePlans.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name} — {money(p.price, p.currency)} за {days(p.periodDays)}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Свой срок, дней" hint="Пусто — берём срок из тарифа">
          <input
            className="gd-input"
            inputMode="numeric"
            value={customDays}
            onChange={(e) => setCustomDays(e.target.value)}
            placeholder={plan ? String(plan.periodDays) : "30"}
          />
        </Field>

        <label style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={registerPayment}
            onChange={(e) => setRegisterPayment(e.target.checked)}
            style={{ width: 16, height: 16, accentColor: "var(--gd-gold)" }}
          />
          Записать оплату {plan ? money(plan.price, plan.currency) : ""} в календарь прибыли
        </label>

        <div style={{ fontSize: 12.5, color: "var(--gd-faint)", lineHeight: 1.5 }}>
          {user.expiresAt
            ? `Сейчас оплачено до ${date(user.expiresAt)} — новый срок добавится к остатку, а не съест его.`
            : "Подписки нет, срок начнётся с сегодняшнего дня."}{" "}
          Расход трафика обнулится.
        </div>

        {error && <div className="gd-error">{error}</div>}
      </div>
    </Modal>
  );
}
