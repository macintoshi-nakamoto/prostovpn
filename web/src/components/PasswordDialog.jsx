import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useT } from "../lib/i18n/index.jsx";
import "./password-dialog.css";

/**
 * Смена пароля из кабинета.
 *
 * Текущий пароль спрашивает бэкенд обязательно, поэтому поле здесь тоже
 * обязательное. После смены все сессии гасятся — об этом честно
 * предупреждаем: человек введёт новый пароль заново на каждом устройстве.
 */
export function PasswordDialog({ open, onClose, onDone }) {
  const t = useT();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      setCurrent("");
      setNext("");
      setRepeat("");
      setError("");
      setBusy(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (next.length < 8) {
      setError(t("password.short"));
      return;
    }
    if (next !== repeat) {
      setError(t("password.mismatch"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.changePassword(current, next);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("password.failed"));
      setBusy(false);
    }
  };

  return (
    <div className="pd-overlay" onMouseDown={onClose}>
      <form className="pd" onMouseDown={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>{t("password.title")}</h2>
        <p className="pd-sub">{t("password.sub")}</p>

        <label className="pd-field">
          <span>{t("password.current")}</span>
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
            autoFocus
          />
        </label>
        <label className="pd-field">
          <span>{t("password.next")}</span>
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            placeholder={t("password.placeholder")}
            autoComplete="new-password"
          />
        </label>
        <label className="pd-field">
          <span>{t("password.repeat")}</span>
          <input
            type="password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            autoComplete="new-password"
          />
        </label>

        {error && <div className="pd-error">{error}</div>}

        <div className="pd-actions">
          <button type="button" className="btn btn-outline" onClick={onClose}>
            {t("password.cancel")}
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? t("password.busy") : t("password.submit")}
          </button>
        </div>
      </form>
    </div>
  );
}
