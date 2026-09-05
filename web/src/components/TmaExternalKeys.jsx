import { useEffect, useLayoutEffect, useState } from "react";
import { Sheet } from "./Sheet.jsx";
import { Flag } from "./Flags.jsx";
import { api, ApiError } from "../lib/api";
import { isTma, tmaHaptic, tmaOpenApp, tmaOpenDeep } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Ключи для устройств.
 *
 * Всё про установку живёт на своём экране, поэтому здесь одна задача:
 * посмотреть выпущенное, добавить ещё, убрать лишнее. Заходят на
 * полминуты — отсюда лист снизу, а не страница.
 *
 * Ключи двух видов, и они не взаимозаменяемы: Happ и подобные берут
 * ссылку-подписку (одна на все страны, обновляется сама), AmneziaVPN —
 * готовый ключ vpn:// на одну страну. Отсюда вкладки: в общем списке
 * пришлось бы в каждой строке объяснять, что это за ключ.
 */

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
const CHEV = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M8 10l4-4 4 4" />
    <path d="M16 14l-4 4-4-4" />
  </svg>
);

/** Строка со ссылкой и копированием. Слева может стоять выбор страны. */
function Link({ value, lead, copied, onCopy, t }) {
  return (
    <div className="kx-link">
      {lead}
      <span className="kx-link-v">{value}</span>
      <button type="button" className="kx-icon" aria-label={t("su.copyAria")} onClick={onCopy}>
        {copied ? CHECK : COPY}
      </button>
    </div>
  );
}

/** Ссылка-подписка: имя своё, ключ один на все страны. */
function SubRow({ item, busy, copied, onCopy, onRename, onRevoke, t }) {
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
        <>
          <Link value={item.url_vless} copied={copied} onCopy={onCopy} t={t} />
          {/* Внутри Telegram схему сначала дёргаем прямо из вебвью — если
              приложение открылось, страница уйдёт в фон. Не ушла за полторы
              секунды — значит вебвью схему заглушил, и тогда идём через
              трамплин /open.html во внешнем браузере. */}
          <a
            className="kx-open"
            href={`happ://add/${item.url_vless}`}
            onClick={(e) => {
              if (!isTma()) return;
              e.preventDefault();
              tmaHaptic("light");
              tmaOpenDeep(`happ://add/${item.url_vless}`);
            }}
          >
            {t("su.openIn", { app: "Happ" })}
          </a>
        </>
      ) : (
        <span className="kx-gone">{t("keys.gone")}</span>
      )}

      <span className="kx-when">{item.last_used_at ? t("keys.used") : t("keys.neverUsed")}</span>
    </div>
  );
}

/**
 * Ключ Amnezia. Имени у него нет — есть страна, менять нечего. Внутри
 * одного ключа стран бывает несколько (наследие прежней выдачи), поэтому
 * страна переключается флагом, как на экране установки.
 */
function VpnRow({ group, busy, copied, onCopy, onRevoke, t }) {
  const [at, setAt] = useState(0);
  const [copiedBackup, setCopiedBackup] = useState(false);
  const link = group.links[Math.min(at, group.links.length - 1)];

  const copyBackup = async () => {
    if (!link.vless_url) return;
    try {
      await navigator.clipboard.writeText(link.vless_url);
      tmaHaptic("light");
      setCopiedBackup(true);
      setTimeout(() => setCopiedBackup(false), 1400);
    } catch {}
  };

  return (
    <div className="kx-row">
      <div className="kx-top">
        <span className="kx-name kx-name-flat">{t("account.tmaKeyN", { n: group.slot })}</span>
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

      <Link
        value={link.vpn_url}
        copied={copied}
        onCopy={() => onCopy(link.vpn_url)}
        t={t}
        lead={
          <label className="kx-flag" title={link.country || link.server}>
            <Flag code={link.country_code} title={link.country || link.server} />
            {group.links.length > 1 && <span className="kx-flag-ic">{CHEV}</span>}
            {group.links.length > 1 && (
              <select
                className="kx-native"
                value={String(at)}
                onChange={(e) => {
                  tmaHaptic("light");
                  setAt(Number(e.target.value));
                }}
              >
                {group.links.map((one, i) => (
                  <option key={one.server_id} value={String(i)}>
                    {one.country || one.server}
                  </option>
                ))}
              </select>
            )}
          </label>
        }
      />

      <button
        type="button"
        className="kx-open"
        onClick={() => {
          tmaHaptic("light");
          tmaOpenApp(link.vpn_url);
        }}
      >
        {t("su.openIn", { app: "AmneziaVPN" })}
      </button>

      {/* Запасная ссылка того же узла по Reality — если основной ключ
          режут на мобильном интернете. Вставляется в AmneziaVPN как
          обычный ключ. */}
      {link.vless_url && (
        <Link
          value={link.vless_url}
          copied={copiedBackup}
          onCopy={copyBackup}
          t={t}
          lead={<span className="kx-link-k">{t("keys.backup")}</span>}
        />
      )}

      <span className="kx-when">
        {(link.country || link.server) +
          " · " +
          (link.is_connected ? t("keys.online") : t("keys.neverUsed"))}
      </span>
    </div>
  );
}

export function TmaExternalKeys({ open, onClose, initialTab = "sub" }) {
  const { t } = useI18n();

  const [tab, setTab] = useState(initialTab);
  // С экрана установки лист открывают сразу на нужной вкладке.
  useEffect(() => {
    if (open) setTab(initialTab);
  }, [open, initialTab]);
  const [keys, setKeys] = useState(null);
  const [ios, setIos] = useState(null);
  // Сколько устройств ещё можно добавить по тарифу: ключ и ссылка — это
  // устройство, и сверх лимита сервер их не выпустит.
  const [devLeft, setDevLeft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");

  // Бегунок вкладок ставим по замеру кнопки: надписи разной длины, а доли
  // ширины здесь дают промах.
  const [tabsEl, setTabsEl] = useState(null);
  const [pill, setPill] = useState(null);

  const loadSubs = () =>
    api
      .subscriptionKeys()
      .then((r) => setKeys(Array.isArray(r) ? r : []))
      .catch(() => setKeys([]));

  const loadIos = () =>
    api
      .account()
      .then((r) => {
        setIos(r?.ios || {});
        setDevLeft(typeof r?.devices_left === "number" ? r.devices_left : null);
      })
      .catch(() => setIos({}));

  useEffect(() => {
    if (!open) return;
    loadSubs();
    loadIos();
  }, [open]);

  useLayoutEffect(() => {
    if (!tabsEl) return undefined;
    const place = () => {
      const on = tabsEl.querySelector(".kx-tab.is-on");
      if (!on) return;
      const c = tabsEl.getBoundingClientRect();
      const b = on.getBoundingClientRect();
      if (!b.width) return;
      setPill({ left: Math.round(b.left - c.left), width: Math.round(b.width) });
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(tabsEl);
    return () => ro.disconnect();
  }, [tabsEl, tab]);

  const copy = async (value, mark) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      tmaHaptic("light");
      setCopied(mark);
      setTimeout(() => setCopied((cur) => (cur === mark ? "" : cur)), 1400);
    } catch {}
  };

  const fail = (err) => {
    const code = err instanceof ApiError ? err.code : "";
    setError(
      code === "no_subscription"
        ? t("account.iosNoSubscription")
        : err instanceof ApiError
          ? err.message
          : t("keys.failed"),
    );
  };

  const limit = ios?.max_keys || 5;

  // ── ссылки-подписки ───────────────────────────────────────────────────
  const subs = keys || [];
  const byPlan = (n) => (devLeft == null ? n : Math.min(n, devLeft));
  const subLeft = byPlan(Math.max(limit - subs.length, 0));

  const issueSub = () => {
    setBusy(true);
    setError("");
    tmaHaptic("light");
    api
      .issueSubscriptionKey(t("keys.autoName", { n: subs.length + 1 }))
      .then(() => Promise.all([loadSubs(), loadIos()]))
      .catch(fail)
      .finally(() => setBusy(false));
  };

  // ── ключи Amnezia ─────────────────────────────────────────────────────
  const groups = [];
  for (const key of ios?.keys || []) {
    const found = groups.find((g) => g.slot === key.slot);
    if (found) found.links.push(key);
    else groups.push({ slot: key.slot, links: [key] });
  }
  const servers = ios?.servers || [];
  const vpnLeft = byPlan(Math.max(limit - groups.length, 0));

  const issueVpn = (serverId) => {
    setBusy(true);
    setError("");
    tmaHaptic("light");
    const call = ios?.available ? api.addIosKey(serverId) : api.enableIos(serverId);
    call
      .then(loadIos)
      .catch(fail)
      .finally(() => setBusy(false));
  };

  const revokeVpn = (slot) => {
    setBusy(true);
    setError("");
    api
      .deleteIosKey(slot)
      .then(loadIos)
      .catch(fail)
      .finally(() => setBusy(false));
  };

  const TABS = [
    { id: "sub", title: t("keys.tabSub") },
    { id: "vpn", title: "AmneziaVPN" },
  ];
  const loading = tab === "sub" ? keys === null : ios === null;
  const left = tab === "sub" ? subLeft : vpnLeft;
  const canAddVpn = vpnLeft > 0 && servers.length > 0 && !busy;

  return (
    <Sheet open={open} title={t("keys.title")} sub={t("keys.lead")} onClose={onClose}>
      <div className="kx">
        <div className="kx-tabs" role="tablist" ref={setTabsEl}>
          {pill && (
            <span
              className="kx-pill"
              style={{ transform: `translateX(${pill.left}px)`, width: pill.width }}
            />
          )}
          {TABS.map((one) => (
            <button
              key={one.id}
              type="button"
              role="tab"
              aria-selected={tab === one.id}
              className={"kx-tab" + (tab === one.id ? " is-on" : "")}
              onClick={() => {
                if (one.id === tab) return;
                tmaHaptic("light");
                setError("");
                setTab(one.id);
              }}
            >
              {one.title}
            </button>
          ))}
        </div>

        {loading ? (
          <p className="kx-gone">{t("su.waitFile")}</p>
        ) : tab === "sub" ? (
          subs.map((item) => (
            <SubRow
              key={item.id}
              item={item}
              busy={busy}
              copied={copied === "s" + item.id}
              onCopy={() => copy(item.url_vless, "s" + item.id)}
              onRename={(label) =>
                api.renameSubscriptionKey(item.id, label).then(loadSubs).catch(() => {})
              }
              onRevoke={() => {
                setBusy(true);
                api
                  .revokeSubscriptionKey(item.id)
                  .then(() => Promise.all([loadSubs(), loadIos()]))
                  .catch(() => {})
                  .finally(() => setBusy(false));
              }}
              t={t}
            />
          ))
        ) : (
          groups.map((group) => (
            <VpnRow
              key={group.slot}
              group={group}
              busy={busy}
              copied={copied === "v" + group.slot}
              onCopy={(url) => copy(url, "v" + group.slot)}
              onRevoke={() => revokeVpn(group.slot)}
              t={t}
            />
          ))
        )}

        {error && <p className="kx-error">{error}</p>}

        {tab === "sub" ? (
          <button
            type="button"
            className="kx-add"
            disabled={busy || subLeft === 0}
            onClick={issueSub}
          >
            <span className="kx-add-ic">{PLUS}</span>
            {t("keys.issue")}
            <span className="kx-left">
              {left > 0 ? t("keys.left", { n: left }) : t("keys.full")}
            </span>
          </button>
        ) : (
          // Ключ Amnezia выдаётся на одну страну, поэтому кнопка сразу
          // спрашивает какую — системным списком, как везде на установке.
          <label className={"kx-add" + (canAddVpn ? "" : " is-off")}>
            <span className="kx-add-ic">{PLUS}</span>
            {t("keys.issue")}
            <span className="kx-left">
              {left > 0 ? t("keys.left", { n: left }) : t("keys.full")}
            </span>
            {canAddVpn && (
              <select
                className="kx-native"
                value=""
                onChange={(e) => e.target.value && issueVpn(Number(e.target.value))}
              >
                <option value="">{t("keys.pickCountry")}</option>
                {servers.map((one) => (
                  <option key={one.id} value={String(one.id)}>
                    {one.country || one.name}
                  </option>
                ))}
              </select>
            )}
          </label>
        )}
      </div>
    </Sheet>
  );
}
