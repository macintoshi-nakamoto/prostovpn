import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { Sheet } from "./Sheet.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import { tmaHaptic } from "../lib/telegram.js";

// Данные для входа на сайт.
//
// В мини-приложении их не спрашивают: личность подтверждает подпись Telegram.
// Но с компьютера зайти нечем, а выданный логин с паролем человек ни разу не
// видел — поэтому показываем их здесь и даём заменить на свои.
//
// Пароль виден, только пока он выданный нами. Как только человек задал свой,
// сервер перестаёт его отдавать: это уже его секрет, а не наша выдача.
export default function WebLoginSheet({ open, onClose }) {
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [copied, setCopied] = useState(null);
  const [editing, setEditing] = useState(false);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError("");
    setSaved(false);
    api
      .credentials()
      .then((res) => {
        setData(res);
        setLogin(res.login || "");
      })
      .catch((err) => setError(err?.message || "не удалось загрузить"));
  }, [open]);

  const copy = async (value, key) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      tmaHaptic("light");
      setCopied(key);
      setTimeout(() => setCopied((cur) => (cur === key ? null : cur)), 1400);
    } catch {}
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.setCredentials(
        login !== data?.login ? login : null,
        password || null,
      );
      setData(res);
      setPassword("");
      setEditing(false);
      setSaved(true);
      tmaHaptic("success");
    } catch (err) {
      setError(err?.message || "не удалось сохранить");
    } finally {
      setBusy(false);
    }
  };

  const canSave =
    !busy && ((login && login !== data?.login) || (password && password.length >= 8));

  return (
    <Sheet open={open} title={t("account.webLoginTitle")} onClose={onClose}>
      <p className="wl-lead">{t("account.webLoginLead")}</p>

      {error && <p className="wl-error">{error}</p>}

      {data && (
        <div className="wl-fields">
          <button type="button" className="wl-field" onClick={() => copy(data.login, "login")}>
            <span className="wl-field-label">{t("account.webLoginLogin")}</span>
            <span className="wl-field-value">{data.login}</span>
            <span className="wl-field-hint">
              {copied === "login" ? t("account.webLoginCopied") : ""}
            </span>
          </button>

          {data.password ? (
            <button
              type="button"
              className="wl-field"
              onClick={() => copy(data.password, "password")}
            >
              <span className="wl-field-label">{t("account.webLoginPassword")}</span>
              <span className="wl-field-value wl-mono">{data.password}</span>
              <span className="wl-field-hint">
                {copied === "password" ? t("account.webLoginCopied") : ""}
              </span>
            </button>
          ) : (
            <p className="wl-note">{t("account.webLoginSet")}</p>
          )}
        </div>
      )}

      {saved && <p className="wl-saved">{t("account.webLoginSaved")}</p>}

      {!editing ? (
        <button type="button" className="wl-btn wl-btn-ghost" onClick={() => setEditing(true)}>
          {t("account.webLoginOwn")}
        </button>
      ) : (
        <div className="wl-form">
          <label className="wl-input-wrap">
            <span className="wl-input-label">{t("account.webLoginLogin")}</span>
            <input
              className="wl-input"
              value={login}
              onChange={(e) => setLogin(e.target.value.trim())}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              maxLength={64}
            />
          </label>
          {data?.is_generated && (
            <label className="wl-input-wrap">
              <span className="wl-input-label">{t("account.webLoginPassword")}</span>
              <input
                className="wl-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                maxLength={128}
              />
            </label>
          )}
          <p className="wl-hint">{t("account.webLoginOwnHint")}</p>
          <button type="button" className="wl-btn" disabled={!canSave} onClick={save}>
            {t("account.webLoginSave")}
          </button>
        </div>
      )}
    </Sheet>
  );
}
