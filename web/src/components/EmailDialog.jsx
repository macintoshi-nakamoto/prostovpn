import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { tmaHaptic } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";
import { SheetShell } from "./SheetShell.jsx";

// Почта — нижним листом, той же породы, что смена пароля. Клавиатуру не
// открываем сами: человек тапнет поле, когда будет готов.
export function EmailDialog({ open, email, onClose, onChanged }) {
  const { t } = useI18n();
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setValue(email || "");
      setError("");
      setBusy(false);
    }
  }, [open, email]);

  const save = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api.setEmail(value.trim());
      tmaHaptic("medium");
      onClose();
      onChanged();
      try {
        window.Telegram?.WebApp?.showAlert?.(t("account.tmaEmailDone"));
      } catch {}
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      setError(
        code === "email_taken"
          ? t("account.emailTaken")
          : err instanceof ApiError
            ? err.message
            : t("account.emailFailed"),
      );
      setBusy(false);
    }
  };

  return (
    <SheetShell open={open} onClose={onClose} onSubmit={save}>
      <h2>{t("account.tmaEmailTitle")}</h2>
      <p className="pd-sub">{t("account.tmaEmailSub")}</p>

      <label className="pd-field">
        <span>{t("account.fieldEmail")}</span>
        <input
          type="email"
          required
          inputMode="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>

      {error && <div className="pd-error">{error}</div>}

      <div className="pd-actions">
        <button type="button" className="btn btn-outline" onClick={onClose}>
          {t("password.cancel")}
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? t("password.busy") : t("account.save")}
        </button>
      </div>
    </SheetShell>
  );
}
