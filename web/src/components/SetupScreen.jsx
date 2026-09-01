import { useEffect, useMemo, useState } from "react";
import { ScreenShell } from "./ScreenShell.jsx";
import { api } from "../lib/api";
import { isTma, tmaHaptic, tmaOpenApp, tmaOpenLink } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Экран установки.
 *
 * Два вопроса подряд — какое устройство и какая программа, — и дальше
 * карточки-шаги: поставить, добавить ключ (или войти), подключиться.
 * Ни вкладок, ни развилок: на каждом шаге ровно одно действие, и оно
 * относится к тому, что выбрано сверху.
 *
 * Программ у нас несколько на одно устройство, поэтому выбора два, а не
 * один: второй заранее стоит на том, что мы советуем, и трогать его не
 * обязательно.
 */

const APPSTORE_AMNEZIA = "https://apps.apple.com/app/amneziavpn/id1600529900";

/** Устройства в порядке распространённости. */
const DEVICES = ["android", "ios", "win", "mac", "tv"];

/**
 * Что чем настраивается.
 *
 *   ours — наше приложение: скачать и войти логином, ключ не нужен;
 *   vpn  — AmneziaVPN: ей нужен готовый ключ vpn://, ссылку она не берёт;
 *   sub  — Happ и подобные: берут ссылку-подписку и обновляют её сами.
 */
const APPS = {
  prosto: {
    name: "Prosto VPN",
    kind: "ours",
    on: { android: 1, win: 1, mac: 1, tv: 1 },
  },
  amnezia: {
    name: "AmneziaVPN",
    kind: "vpn",
    on: { ios: 1, android: 1, mac: 1, win: 1 },
    store: {
      ios: APPSTORE_AMNEZIA,
      mac: APPSTORE_AMNEZIA,
      android: "https://play.google.com/store/apps/details?id=org.amnezia.vpn",
      win: "https://github.com/amnezia-vpn/amnezia-client/releases/latest",
    },
  },
  happ: {
    name: "Happ",
    kind: "sub",
    on: { ios: 1, android: 1, mac: 1, win: 1 },
    deep: (url) => `happ://add/${encodeURIComponent(url)}`,
    store: {
      ios: "https://apps.apple.com/app/happ-proxy-utility/id6504287215",
      mac: "https://apps.apple.com/app/happ-proxy-utility/id6504287215",
      android: "https://play.google.com/store/apps/details?id=com.happproxy",
      win: "https://github.com/Happ-proxy/happ-desktop/releases/latest",
    },
  },
  hiddify: {
    name: "Hiddify",
    kind: "sub",
    on: { ios: 1, android: 1, mac: 1, win: 1 },
    deep: (url) => `hiddify://import/${url}`,
    store: {
      ios: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532",
      android: "https://play.google.com/store/apps/details?id=app.hiddify.com",
      mac: "https://github.com/hiddify/hiddify-app/releases/latest",
      win: "https://github.com/hiddify/hiddify-app/releases/latest",
    },
  },
  streisand: {
    name: "Streisand",
    kind: "sub",
    on: { ios: 1, mac: 1 },
    deep: (url) => `streisand://import/${url}`,
    store: {
      ios: "https://apps.apple.com/app/streisand/id6450534064",
      mac: "https://apps.apple.com/app/streisand/id6450534064",
    },
  },
  v2rayng: {
    name: "v2rayNG",
    kind: "sub",
    on: { android: 1 },
    deep: (url) => `v2rayng://install-sub?url=${encodeURIComponent(url)}`,
    store: { android: "https://play.google.com/store/apps/details?id=com.v2ray.ang" },
  },
  nekobox: {
    name: "NekoBox",
    kind: "sub",
    on: { android: 1 },
    deep: null,
    store: { android: "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest" },
  },
};

/** Что советуем по умолчанию: своё приложение там, где оно есть. */
const DEFAULT_APP = { android: "prosto", win: "prosto", mac: "prosto", tv: "prosto", ios: "amnezia" };

/** Наша сборка под устройство. Телевизор берёт андроидную. */
const OUR_BUILD = { win: "windows", android: "android", mac: "macos", tv: "android" };

function guessDevice() {
  if (typeof navigator === "undefined") return "android";
  const ua = navigator.userAgent || "";
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  if (/Android/i.test(ua)) return "android";
  if (/Macintosh|Mac OS X/i.test(ua)) return "mac";
  if (/Windows/i.test(ua)) return "win";
  return "android";
}

/* Значок раздела — шестерёнка в дышащих кольцах. */
const GEAR = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="3.2" />
    <path d="M19.4 15a1.6 1.6 0 0 0 .32 1.77l.06.06a1.94 1.94 0 1 1-2.75 2.75l-.06-.06a1.6 1.6 0 0 0-1.77-.32 1.6 1.6 0 0 0-.97 1.46V21a1.94 1.94 0 0 1-3.88 0v-.1a1.6 1.6 0 0 0-1.05-1.46 1.6 1.6 0 0 0-1.77.32l-.06.06a1.94 1.94 0 1 1-2.75-2.75l.06-.06a1.6 1.6 0 0 0 .32-1.77 1.6 1.6 0 0 0-1.46-.97H3a1.94 1.94 0 0 1 0-3.88h.1a1.6 1.6 0 0 0 1.46-1.05 1.6 1.6 0 0 0-.32-1.77l-.06-.06a1.94 1.94 0 1 1 2.75-2.75l.06.06a1.6 1.6 0 0 0 1.77.32H9a1.6 1.6 0 0 0 .97-1.46V3a1.94 1.94 0 0 1 3.88 0v.1a1.6 1.6 0 0 0 .97 1.46 1.6 1.6 0 0 0 1.77-.32l.06-.06a1.94 1.94 0 1 1 2.75 2.75l-.06.06a1.6 1.6 0 0 0-.32 1.77V9a1.6 1.6 0 0 0 1.46.97H21a1.94 1.94 0 0 1 0 3.88h-.1a1.6 1.6 0 0 0-1.46.97z" />
  </svg>
);

/* Значки шагов: скачать, ключ, подключиться. */
const IC_DOWNLOAD = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3v12" />
    <path d="M7.5 10.5L12 15l4.5-4.5" />
    <path d="M4 18.5h16" />
  </svg>
);
const IC_KEY = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="7.5" cy="16.5" r="3.8" />
    <path d="M10.2 13.8L20 4" />
    <path d="M16.5 7.5l2.5 2.5" />
    <path d="M14 10l2 2" />
  </svg>
);
const IC_LOCK = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4.5" y="10.5" width="15" height="10" rx="2.6" />
    <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
  </svg>
);
const IC_LINK = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M10 13a4.5 4.5 0 0 0 6.4.4l2.6-2.6a4.5 4.5 0 0 0-6.4-6.4L11.4 6" />
    <path d="M14 11a4.5 4.5 0 0 0-6.4-.4L5 13.2a4.5 4.5 0 0 0 6.4 6.4L12.6 18" />
  </svg>
);
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
const EYE = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" />
    <circle cx="12" cy="12" r="2.7" />
  </svg>
);
const EYE_OFF = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 4l16 16" />
    <path d="M9.6 5.7A11 11 0 0 1 12 5.5c6.4 0 10 6.5 10 6.5a18 18 0 0 1-3.5 4.2" />
    <path d="M6.4 7.7A18 18 0 0 0 2 12s3.6 6.5 10 6.5c1 0 1.9-.1 2.7-.4" />
    <path d="M9.9 9.9a2.7 2.7 0 0 0 3.8 3.8" />
  </svg>
);
const CHEV = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M8 10l4-4 4 4" />
    <path d="M16 14l-4 4-4-4" />
  </svg>
);

/**
 * Выбор из списка.
 *
 * Внутри настоящий select: в Telegram он открывает системный список
 * устройства — привычный, с прокруткой и крупными строками. Своё меню
 * пришлось бы рисовать и чинить под каждую оболочку.
 */
function Pick({ label, value, options, onChange }) {
  return (
    <label className="su-pick">
      <span className="su-pick-k">{label}</span>
      <span className="su-pick-v">
        {options.find((o) => o.id === value)?.title || ""}
        <span className="su-pick-ic">{CHEV}</span>
      </span>
      <select
        className="su-pick-native"
        value={value}
        onChange={(e) => {
          tmaHaptic("light");
          onChange(e.target.value);
        }}
      >
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.title}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Строка со значением: подпись, значение, кнопки. */
function Field({ label, value, secret, copied, onCopy, t }) {
  const [shown, setShown] = useState(false);
  if (!value) return null;
  const hidden = secret && !shown;
  return (
    <div className="su-field">
      <span className="su-field-k">{label}</span>
      <span className="su-field-v su-mono">
        {hidden ? "•".repeat(Math.min(value.length, 28)) : value}
      </span>
      {secret && (
        <button
          type="button"
          className="su-field-b"
          aria-label={shown ? t("su.hidePwd") : t("su.showPwd")}
          onClick={() => setShown((on) => !on)}
        >
          {shown ? EYE_OFF : EYE}
        </button>
      )}
      <button type="button" className="su-field-b" aria-label={t("su.copyAria")} onClick={onCopy}>
        {copied ? CHECK : COPY}
      </button>
    </div>
  );
}

/** Карточка шага: значок слева, заголовок и текст справа, действия снизу. */
function Step({ icon, title, text, children }) {
  return (
    <div className="ap-card su-step">
      <div className="su-step-head">
        <span className="su-step-ic">{icon}</span>
        <span className="su-step-body">
          <span className="su-step-t">{title}</span>
          {text && <span className="su-step-s">{text}</span>}
        </span>
      </div>
      {children}
    </div>
  );
}

export function SetupScreen({ open, onClose, onKeys }) {
  const { t } = useI18n();

  const [device, setDevice] = useState(guessDevice);
  const [app, setApp] = useState(() => DEFAULT_APP[guessDevice()]);
  const [downloads, setDownloads] = useState(null);
  const [creds, setCreds] = useState(null);
  const [keys, setKeys] = useState(null);
  const [vpnKeys, setVpnKeys] = useState(null);
  const [country, setCountry] = useState(0);
  const [copied, setCopied] = useState("");

  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    api.downloads().then((r) => alive && setDownloads(Array.isArray(r) ? r : [])).catch(() => alive && setDownloads([]));
    api.credentials().then((r) => alive && setCreds(r)).catch(() => alive && setCreds({}));
    api.subscriptionKeys().then((r) => alive && setKeys(Array.isArray(r) ? r : [])).catch(() => alive && setKeys([]));
    api.account().then((r) => alive && setVpnKeys(r?.ios?.keys || [])).catch(() => alive && setVpnKeys([]));
    return () => {
      alive = false;
    };
  }, [open]);

  const copy = async (value, key) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      tmaHaptic("light");
      setCopied(key);
      setTimeout(() => setCopied((cur) => (cur === key ? "" : cur)), 1400);
    } catch {}
  };

  // Сменили устройство — прежняя программа могла под него не подходить.
  const pickDevice = (id) => {
    setDevice(id);
    if (!APPS[app]?.on[id]) setApp(DEFAULT_APP[id]);
  };

  const appList = useMemo(
    () =>
      Object.entries(APPS)
        .filter(([, one]) => one.on[device])
        .map(([id, one]) => ({ id, title: one.name })),
    [device],
  );

  const meta = APPS[app] || APPS[DEFAULT_APP[device]];
  const file = (downloads || []).find((r) => r.platform === OUR_BUILD[device]);
  const subUrl = (keys || []).find((k) => k.url)?.url_vless || "";

  // По одному ключу на страну, а не по набору.
  //
  // Ключ Amnezia выдаётся на одну страну (набор ios-N), и стран у человека
  // столько, сколько он ключей завёл. Раньше здесь брался первый набор —
  // и страны из остальных просто не показывались: ключ на Польшу лежал в
  // третьем наборе и в списке не появлялся. Наборы с двумя странами
  // остались с прежних времён, поэтому одну и ту же страну отсеиваем:
  // человеку нужен выбор стран, а не список наборов.
  const vpnSet = useMemo(() => {
    const seen = new Set();
    return (vpnKeys || []).filter((k) => {
      const name = k.country || k.server || String(k.server_id);
      if (seen.has(name)) return false;
      seen.add(name);
      return true;
    });
  }, [vpnKeys]);
  const vpn = vpnSet[Math.min(country, Math.max(vpnSet.length - 1, 0))] || null;

  return (
    // Внутри Telegram своя шапка не нужна: сверху уже стоит шапка клиента
    // с системной стрелкой, и вторая полоска с названием только съедает экран.
    // На сайте она остаётся — там в ней живёт кнопка «назад».
    <ScreenShell
      open={open}
      title={t("su.title")}
      back={!isTma()}
      headless={isTma()}
      onClose={onClose}
    >
      <div className="su">
        <div className="ap-card su-head">
          <span className="su-gear">{GEAR}</span>
          <span className="ap-head-body">
            <span className="ap-title">{t("su.heroTitle")}</span>
            <span className="ap-sub">{t("su.heroLead")}</span>
          </span>
        </div>

        <div className="su-picks">
          <Pick
            label={t("su.device")}
            value={device}
            options={DEVICES.map((id) => ({ id, title: t(`su.dev.${id}`) }))}
            onChange={pickDevice}
          />
          <Pick label={t("su.app")} value={meta === APPS[app] ? app : DEFAULT_APP[device]} options={appList} onChange={setApp} />
        </div>

        {/* ── шаг 1: поставить программу ──────────────────────────────── */}
        <Step
          icon={IC_DOWNLOAD}
          title={t("su.stepInstall", { app: meta.name })}
          text={meta.kind === "ours" ? t("su.installOurs") : t("su.installOther", { app: meta.name })}
        >
          {meta.kind === "ours" ? (
            downloads === null ? (
              <span className="su-wait">{t("su.waitFile")}</span>
            ) : file?.url ? (
              <button
                type="button"
                className="ap-cta su-cta"
                onClick={() => {
                  tmaHaptic("light");
                  tmaOpenLink(file.url);
                }}
              >
                {t("su.download", { os: t(`su.dev.${device}`) })}
              </button>
            ) : (
              <span className="su-wait">{t("su.noFile")}</span>
            )
          ) : (
            <a className="ap-cta su-cta" href={meta.store?.[device]} target="_blank" rel="noreferrer noopener">
              {t("su.install", { app: meta.name })}
            </a>
          )}
        </Step>

        {/* ── шаг 2: войти или добавить ключ ──────────────────────────── */}
        {meta.kind === "ours" && (
          <Step icon={IC_LOCK} title={t("su.stepSignIn")} text={t("su.ourLead")}>
            <Field
              label={t("account.webLoginLogin")}
              value={creds?.login || ""}
              copied={copied === "login"}
              onCopy={() => copy(creds?.login, "login")}
              t={t}
            />
            {creds?.password ? (
              <Field
                label={t("account.webLoginPassword")}
                value={creds.password}
                secret
                copied={copied === "pwd"}
                onCopy={() => copy(creds.password, "pwd")}
                t={t}
              />
            ) : creds?.is_generated === false ? (
              <span className="su-wait">{t("su.ownPassword")}</span>
            ) : null}
          </Step>
        )}

        {meta.kind === "vpn" && (
          <Step icon={IC_KEY} title={t("su.stepKey")} text={t("su.amneziaLead")}>
            {vpnKeys === null ? (
              <span className="su-wait">{t("su.waitFile")}</span>
            ) : vpn ? (
              <>
                {vpnSet.length > 1 && (
                  <div className="su-os">
                    {vpnSet.map((one, i) => (
                      <button
                        key={one.slot + "-" + one.server_id}
                        type="button"
                        className={"su-os-b" + (i === country ? " is-on" : "")}
                        onClick={() => {
                          tmaHaptic("light");
                          setCountry(i);
                        }}
                      >
                        {one.country || one.server}
                      </button>
                    ))}
                  </div>
                )}
                <Field
                  label={t("su.key")}
                  value={vpn.vpn_url}
                  copied={copied === "vpn"}
                  onCopy={() => copy(vpn.vpn_url, "vpn")}
                  t={t}
                />
                <button
                  type="button"
                  className="ap-cta su-cta su-cta-alt"
                  onClick={() => {
                    tmaHaptic("light");
                    tmaOpenApp(vpn.vpn_url);
                  }}
                >
                  {t("su.openIn", { app: meta.name })}
                </button>
              </>
            ) : (
              <span className="su-wait">{t("su.noVpnKey")}</span>
            )}
          </Step>
        )}

        {meta.kind === "sub" && (
          <Step icon={IC_KEY} title={t("su.stepKey")} text={t("su.vlessLead")}>
            {keys === null ? (
              <span className="su-wait">{t("su.waitFile")}</span>
            ) : subUrl ? (
              <>
                <Field
                  label={t("su.key")}
                  value={subUrl}
                  copied={copied === "sub"}
                  onCopy={() => copy(subUrl, "sub")}
                  t={t}
                />
                {meta.deep && (
                  <a className="ap-cta su-cta su-cta-alt" href={meta.deep(subUrl)}>
                    {t("su.openIn", { app: meta.name })}
                  </a>
                )}
              </>
            ) : (
              <span className="su-wait">{t("su.noKey")}</span>
            )}
          </Step>
        )}

        {/* ── шаг 3: подключиться ─────────────────────────────────────── */}
        <Step icon={IC_LINK} title={t("su.stepConnect")} text={t("su.connectLead")} />

        <button type="button" className="su-more" onClick={onKeys}>
          {t("su.moreKeys")}
        </button>
      </div>
    </ScreenShell>
  );
}
