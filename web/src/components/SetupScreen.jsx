import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { ScreenShell } from "./ScreenShell.jsx";
import { api } from "../lib/api";
import { isTma, tmaHaptic, tmaOpenLink } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Экран установки.
 *
 * Всё, что нужно для подключения, — на одном экране, без шагов и без
 * листания. Наверху переключатель из трёх положений; под ним ровно то,
 * что требует выбранный способ, и ничего больше:
 *
 *   наше приложение → скачать + логин с паролем (вход по ним, не по ключу);
 *   AmneziaVPN      → поставить из магазина + ключ в его формате;
 *   Happ и другие   → список программ + ключ в формате vless.
 *
 * Ключ виден сразу и всегда: человек приходит сюда взять его, а не нажать
 * «создать». Первую ссылку заводит сервер сам при первом заходе.
 */

/** Наши приложения: вход логином и паролем, ключ им не нужен. */
const OURS = [
  { os: "win", platform: "windows" },
  { os: "android", platform: "android" },
  { os: "mac", platform: "macos" },
];

const APPSTORE_AMNEZIA = "https://apps.apple.com/app/amneziavpn/id1600529900";

/** AmneziaVPN по платформам. Свой формат ключа, свои магазины. */
const AMNEZIA_STORE = {
  ios: APPSTORE_AMNEZIA,
  android: "https://play.google.com/store/apps/details?id=org.amnezia.vpn",
  mac: APPSTORE_AMNEZIA,
  win: "https://github.com/amnezia-vpn/amnezia-client/releases/latest",
};

/**
 * Программы, работающие с обычной подпиской vless.
 *
 * `deep` — ссылка, по которой программа добавляет подписку сама. Где её
 * нет, остаётся копирование, и это нормально.
 */
const VLESS_APPS = [
  {
    id: "happ",
    name: "Happ",
    on: ["ios", "android", "mac", "win"],
    deep: (url) => `happ://add/${encodeURIComponent(url)}`,
    store: {
      ios: "https://apps.apple.com/app/happ-proxy-utility/id6504287215",
      android: "https://play.google.com/store/apps/details?id=com.happproxy",
      mac: "https://apps.apple.com/app/happ-proxy-utility/id6504287215",
      win: "https://github.com/Happ-proxy/happ-desktop/releases/latest",
    },
  },
  {
    id: "hiddify",
    name: "Hiddify",
    on: ["ios", "android", "mac", "win"],
    deep: (url) => `hiddify://import/${url}`,
    store: {
      ios: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532",
      android: "https://play.google.com/store/apps/details?id=app.hiddify.com",
      mac: "https://github.com/hiddify/hiddify-app/releases/latest",
      win: "https://github.com/hiddify/hiddify-app/releases/latest",
    },
  },
  {
    id: "streisand",
    name: "Streisand",
    on: ["ios", "mac"],
    deep: (url) => `streisand://import/${url}`,
    store: {
      ios: "https://apps.apple.com/app/streisand/id6450534064",
      mac: "https://apps.apple.com/app/streisand/id6450534064",
    },
  },
  {
    id: "v2rayng",
    name: "v2rayNG",
    on: ["android"],
    deep: (url) => `v2rayng://install-sub?url=${encodeURIComponent(url)}`,
    store: { android: "https://play.google.com/store/apps/details?id=com.v2ray.ang" },
  },
  {
    id: "nekobox",
    name: "NekoBox",
    on: ["android"],
    deep: null,
    store: { android: "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest" },
  },
];

const PLATFORMS = ["ios", "android", "mac", "win"];

/** Наша сборка под платформу, которую выбрали для стороннего приложения. */
const OUR_PLATFORM = { win: "windows", android: "android", mac: "macos" };

function guessPlatform() {
  if (typeof navigator === "undefined") return "android";
  const ua = navigator.userAgent || "";
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  if (/Android/i.test(ua)) return "android";
  if (/Macintosh|Mac OS X/i.test(ua)) return "mac";
  if (/Windows/i.test(ua)) return "win";
  return "android";
}

/* Значок раздела: шестерёнка в расходящихся кольцах. Кольца дышат — экран
   открывается редко, и живой значок сразу говорит, что попал куда надо. */
const GEAR = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="3.2" />
    <path d="M19.4 15a1.6 1.6 0 0 0 .32 1.77l.06.06a1.94 1.94 0 1 1-2.75 2.75l-.06-.06a1.6 1.6 0 0 0-1.77-.32 1.6 1.6 0 0 0-.97 1.46V21a1.94 1.94 0 0 1-3.88 0v-.1a1.6 1.6 0 0 0-1.05-1.46 1.6 1.6 0 0 0-1.77.32l-.06.06a1.94 1.94 0 1 1-2.75-2.75l.06-.06a1.6 1.6 0 0 0 .32-1.77 1.6 1.6 0 0 0-1.46-.97H3a1.94 1.94 0 0 1 0-3.88h.1a1.6 1.6 0 0 0 1.46-1.05 1.6 1.6 0 0 0-.32-1.77l-.06-.06a1.94 1.94 0 1 1 2.75-2.75l.06.06a1.6 1.6 0 0 0 1.77.32H9a1.6 1.6 0 0 0 .97-1.46V3a1.94 1.94 0 0 1 3.88 0v.1a1.6 1.6 0 0 0 .97 1.46 1.6 1.6 0 0 0 1.77-.32l.06-.06a1.94 1.94 0 1 1 2.75 2.75l-.06.06a1.6 1.6 0 0 0-.32 1.77V9a1.6 1.6 0 0 0 1.46.97H21a1.94 1.94 0 0 1 0 3.88h-.1a1.6 1.6 0 0 0-1.46.97z" />
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

/** Строка «подпись — значение — кнопки». Логин, пароль и ключ устроены одинаково. */
function Field({ label, value, mono, secret, copied, onCopy, t }) {
  const [shown, setShown] = useState(false);
  if (!value) return null;
  const hidden = secret && !shown;
  return (
    <div className="su-field">
      <span className="su-field-k">{label}</span>
      <span className={"su-field-v" + (mono ? " su-mono" : "")}>
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

export function SetupScreen({ open, onClose, onKeys }) {
  const { t } = useI18n();

  // "ours" | "amnezia" | "vless"
  const [tab, setTab] = useState("ours");
  const [platform, setPlatform] = useState(guessPlatform);
  const [downloads, setDownloads] = useState(null);
  const [creds, setCreds] = useState(null);
  const [keys, setKeys] = useState(null);
  const [copied, setCopied] = useState("");

  // Бегунок переключателя ставим по измеренной кнопке, а не по доле
  // ширины: проценты внутри calc для left тут считаются не от контейнера,
  // и бегунок приезжал не туда. Замер заодно переживает любые подписи —
  // сегменты не обязаны быть одинаковой ширины.
  //
  // Узел ловим callback-ref, а не useRef: ScreenShell показывает тело не в
  // том же кадре, в котором открывается, и обычный эффект успевал бы
  // отработать по пустому DOM.
  const [segEl, setSegEl] = useState(null);
  const [pill, setPill] = useState(null);

  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    api.downloads().then((r) => alive && setDownloads(Array.isArray(r) ? r : [])).catch(() => alive && setDownloads([]));
    api.credentials().then((r) => alive && setCreds(r)).catch(() => alive && setCreds({}));
    api.subscriptionKeys().then((r) => alive && setKeys(Array.isArray(r) ? r : [])).catch(() => alive && setKeys([]));
    return () => {
      alive = false;
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!segEl) return undefined;
    const place = () => {
      const on = segEl.querySelector(".su-seg-b.is-on");
      if (!on) return;
      const c = segEl.getBoundingClientRect();
      const b = on.getBoundingClientRect();
      if (!b.width) return;
      setPill({ left: Math.round(b.left - c.left), width: Math.round(b.width) });
    };
    place();
    // Поворот экрана, всплывшая клавиатура, смена шрифта — ширина кнопки
    // меняется и без нашего участия.
    const ro = new ResizeObserver(place);
    ro.observe(segEl);
    return () => ro.disconnect();
  }, [segEl, tab]);

  const copy = async (value, key) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      tmaHaptic("light");
      setCopied(key);
      setTimeout(() => setCopied((cur) => (cur === key ? "" : cur)), 1400);
    } catch {}
  };

  const pickTab = (id) => {
    if (id === tab) return;
    tmaHaptic("light");
    setTab(id);
  };

  // Первая живая ссылка. Их может быть несколько — для остальных устройств,
  // — но на виду держим одну: выбирать человеку здесь нечего.
  const key = useMemo(() => (keys || []).find((k) => k.url) || null, [keys]);

  const ourPlatform = OUR_PLATFORM[platform] || "windows";
  const file = (downloads || []).find((r) => r.platform === ourPlatform);
  const vlessApps = VLESS_APPS.filter((a) => a.on.includes(platform));

  const TABS = [
    { id: "ours", title: t("su.tabOurs") },
    { id: "amnezia", title: "Amnezia" },
    { id: "vless", title: t("su.tabOther") },
  ];

  const keyLine = (which) => {
    const value = which === "amnezia" ? key?.url_amnezia : key?.url_vless;
    if (keys === null) return <p className="su-wait">{t("su.waitFile")}</p>;
    if (!value) return <p className="su-wait">{t("su.noKey")}</p>;
    return (
      <Field
        label={t("su.key")}
        value={value}
        mono
        copied={copied === which}
        onCopy={() => copy(value, which)}
        t={t}
      />
    );
  };

  return (
    <ScreenShell open={open} title={t("su.title")} back={!isTma()} onClose={onClose}>
      <div className="su">
        <div className="su-hero">
          <span className="su-gear">{GEAR}</span>
          <span className="su-hero-t">{t("su.heroTitle")}</span>
          <span className="su-hero-s">{t("su.heroLead")}</span>
        </div>

        {/* Переключатель: подложка стеклянная, бегунок едет за выбором. */}
        <div className="su-seg" role="tablist" ref={setSegEl}>
          {pill && (
            <span
              className="su-seg-pill"
              style={{ transform: `translateX(${pill.left}px)`, width: pill.width }}
            />
          )}
          {TABS.map((one) => (
            <button
              key={one.id}
              type="button"
              role="tab"
              aria-selected={tab === one.id}
              className={"su-seg-b" + (tab === one.id ? " is-on" : "")}
              onClick={() => pickTab(one.id)}
            >
              {one.title}
            </button>
          ))}
        </div>

        {tab !== "ours" && (
          <div className="su-os">
            {PLATFORMS.map((id) => (
              <button
                key={id}
                type="button"
                className={"su-os-b" + (platform === id ? " is-on" : "")}
                onClick={() => {
                  tmaHaptic("light");
                  setPlatform(id);
                }}
              >
                {t(`setup.ext.os.${id}`)}
              </button>
            ))}
          </div>
        )}

        {tab === "ours" && (
          <>
            <div className="su-os">
              {OURS.map((one) => (
                <button
                  key={one.os}
                  type="button"
                  className={"su-os-b" + (ourPlatform === one.platform ? " is-on" : "")}
                  onClick={() => {
                    tmaHaptic("light");
                    setPlatform(one.os);
                  }}
                >
                  {t(`setup.ext.os.${one.os}`)}
                </button>
              ))}
            </div>

            {downloads === null ? (
              <p className="su-wait">{t("su.waitFile")}</p>
            ) : file?.url ? (
              <button
                type="button"
                className="ap-cta su-cta"
                onClick={() => {
                  tmaHaptic("light");
                  tmaOpenLink(file.url);
                }}
              >
                {t("su.download", { os: t(`setup.ext.os.${platform}`) })}
              </button>
            ) : (
              <p className="su-wait">{t("su.noFile")}</p>
            )}

            <p className="su-note">{t("su.ourLead")}</p>
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
                mono
                secret
                copied={copied === "pwd"}
                onCopy={() => copy(creds.password, "pwd")}
                t={t}
              />
            ) : creds?.is_generated === false ? (
              <p className="su-note">{t("su.ownPassword")}</p>
            ) : null}
          </>
        )}

        {tab === "amnezia" && (
          <>
            <a
              className="ap-cta su-cta"
              href={AMNEZIA_STORE[platform]}
              target="_blank"
              rel="noreferrer noopener"
            >
              {t("su.install", { app: "AmneziaVPN" })}
            </a>
            <p className="su-note">{t("su.amneziaLead")}</p>
            {keyLine("amnezia")}
          </>
        )}

        {tab === "vless" && (
          <>
            <div className="su-apps">
              {vlessApps.map((app) => (
                <div className="su-app" key={app.id}>
                  <span className="su-app-n">{app.name}</span>
                  <a
                    className="su-app-get"
                    href={app.store[platform]}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {t("setup.ext.install")}
                  </a>
                  {key?.url_vless && app.deep && (
                    <a className="su-app-add" href={app.deep(key.url_vless)}>
                      {t("setup.ext.add")}
                    </a>
                  )}
                </div>
              ))}
            </div>
            <p className="su-note">{t("su.vlessLead")}</p>
            {keyLine("vless")}
          </>
        )}

        {/* Ключи на другие устройства — тихой ссылкой: большинству хватает
            одного, а кому нужен второй, тот знает, что ищет. */}
        {tab !== "ours" && (
          <button type="button" className="su-more" onClick={onKeys}>
            {t("su.moreKeys")}
          </button>
        )}
      </div>
    </ScreenShell>
  );
}
