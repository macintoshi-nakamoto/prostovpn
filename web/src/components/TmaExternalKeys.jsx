import { useEffect, useState } from "react";
import { Sheet } from "./Sheet.jsx";
import { api } from "../lib/api";
import { tmaHaptic } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Ключи для устройств.
 *
 * Всё про установку живёт на своём экране, поэтому здесь осталась одна
 * задача: посмотреть, какие ключи выпущены, выпустить ещё и убрать
 * ненужный. Отсюда и лист снизу вместо полноэкранной страницы — заходят
 * сюда на полминуты.
 *
 * Ключ выпускается сразу, с именем по умолчанию: придумывать название до
 * выпуска незачем, подписать можно потом и не обязательно.
 */

const MAX_KEYS = 5;

const COPY = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="9" y="9" width="11" height="11" rx="2.5" />
    <path d="M15 5.5A2.5 2.5 0 0 0 12.5 3h-7A2.5 2.5 0 0 0 3 5.5v7A2.5 2.5 0 0 0 5.5 15" />
  </svg>
);
const CHECK = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4.5 12.5l5 5 10-11" />
  </svg>
);
const PEN = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 20h4L19 9a2.5 2.5 0 0 0-3.5-3.5L4.5 16.5z" />
    <path d="M14.5 6.5l3 3" />
  </svg>
);
const TRASH = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4.5 6.5h15" />
    <path d="M9 6.5V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v1.5" />
    <path d="M6.5 6.5l1 12A1.5 1.5 0 0 0 9 20h6a1.5 1.5 0 0 0 1.5-1.5l1-12" />
  </svg>
);
const PLUS = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
    <path d="M12 5v14M5 12h14" />
  </svg>
);

/** Одна выпущенная ссылка. */
function Row({ item, busy, copied, onCopy, onRename, onRevoke, t }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(item.label || "");

  const save = () => {
    setEditing(false);
    const next = name.trim();
    if (next !== (item.label || "")) onRename(next);
  };

  return (
    <div className="kx-row">
      <div className="kx-top">
        {editing ? (
          <input
            className="kx-name-input"
            value={name}
            autoFocus
            maxLength={64}
            onChange={(e) => setName(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
              if (e.key === "Escape") {
                setName(item.label || "");
                setEditing(false);
              }
            }}
          />
        ) : (
          <button
            type="button"
            className="kx-name"
            onClick={() => {
              setName(item.label || "");
              setEditing(true);
            }}
          >
            {item.label || t("keys.noLabel")}
            <span className="kx-pen">{PEN}</span>
          </button>
        )}
        <button
          type="button"
          className="kx-icon kx-danger"
          aria-label={t("keys.revoke")}
          disabled={busy}
          onClick={onRevoke}
        >
          {TRASH}
        </button>
      </div>

      {item.url_vless ? (
        <div className="kx-link">
          <span className="kx-link-v">{item.url_vless}</span>
          <button type="button" className="kx-icon" aria-label={t("su.copyAria")} onClick={onCopy}>
            {copied ? CHECK : COPY}
          </button>
        </div>
      ) : (
        // Ссылки нет у тех, что выпущены до того, как мы стали хранить её
        // обратимо. Восстановить нечего — только выпустить новую.
        <span className="kx-gone">{t("keys.gone")}</span>
      )}

      <span className="kx-when">{item.last_used_at ? t("keys.used") : t("keys.neverUsed")}</span>
    </div>
  );
}

export function TmaExternalKeys({ open, onClose }) {
  const { t } = useI18n();

  const [keys, setKeys] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(0);

  const load = () =>
    api
      .subscriptionKeys()
      .then((r) => setKeys(Array.isArray(r) ? r : []))
      .catch(() => setKeys([]));

  useEffect(() => {
    if (open) load();
  }, [open]);

  const list = keys || [];
  const left = Math.max(MAX_KEYS - list.length, 0);

  const issue = () => {
    setBusy(true);
    setError("");
    tmaHaptic("light");
    api
      .issueSubscriptionKey(t("keys.autoName", { n: list.length + 1 }))
      .then(load)
      .catch((problem) => setError(problem?.message || t("keys.failed")))
      .finally(() => setBusy(false));
  };

  const rename = (id, label) => {
    api.renameSubscriptionKey(id, label).then(load).catch(() => {});
  };

  const revoke = (id) => {
    setBusy(true);
    api
      .revokeSubscriptionKey(id)
      .then(load)
      .catch(() => {})
      .finally(() => setBusy(false));
  };

  const copy = async (item) => {
    try {
      await navigator.clipboard.writeText(item.url_vless);
      tmaHaptic("light");
      setCopied(item.id);
      setTimeout(() => setCopied((cur) => (cur === item.id ? 0 : cur)), 1400);
    } catch {}
  };

  return (
    <Sheet open={open} title={t("keys.title")} sub={t("keys.lead")} onClose={onClose}>
      <div className="kx">
        {keys === null ? (
          <p className="kx-gone">{t("su.waitFile")}</p>
        ) : (
          list.map((item) => (
            <Row
              key={item.id}
              item={item}
              busy={busy}
              copied={copied === item.id}
              onCopy={() => copy(item)}
              onRename={(label) => rename(item.id, label)}
              onRevoke={() => revoke(item.id)}
              t={t}
            />
          ))
        )}

        {error && <p className="kx-error">{error}</p>}

        <button type="button" className="kx-add" disabled={busy || left === 0} onClick={issue}>
          <span className="kx-add-ic">{PLUS}</span>
          {t("keys.issue")}
          <span className="kx-left">{left > 0 ? t("keys.left", { n: left }) : t("keys.full")}</span>
        </button>
      </div>
    </Sheet>
  );
}
