import { useEffect, useMemo, useState } from "react";
import { ScreenShell } from "./ScreenShell.jsx";
import { AppStoreSheet } from "./AppStoreSheet.jsx";
import { api } from "../lib/api";
import { isTma, tmaHaptic, tmaOpenLink } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Скачать приложение.
 *
 * Один вопрос — какое устройство, — и дальше список всего, что на него
 * ставится: наше приложение и сторонние. Ключей здесь нет намеренно: они
 * живут в своём разделе, где их выпускают и удаляют. Раньше эти два дела
 * стояли на одном экране, и человек, пришедший просто скачать программу,
 * попадал в выпуск ключей.
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
    store: {
      ios: "https://apps.apple.com/app/streisand/id6450534064",
      mac: "https://apps.apple.com/app/streisand/id6450534064",
    },
  },
  v2rayng: {
    name: "v2rayNG",
    kind: "sub",
    on: { android: 1 },
    store: { android: "https://play.google.com/store/apps/details?id=com.v2ray.ang" },
  },
  nekobox: {
    name: "NekoBox",
    kind: "sub",
    on: { android: 1 },
    store: { android: "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest" },
  },
};

/** Порядок в списке: сначала наше, дальше то, что советуем чаще. */
const ORDER = ["prosto", "amnezia", "happ", "hiddify", "streisand", "v2rayng", "nekobox"];

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

/* Значок раздела — стрелка вниз в дышащих кольцах. */
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

/** Карточка приложения: значок, название, за что отвечает, кнопка установки. */
function AppCard({ icon, title, text, children }) {
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

export function AppsScreen({ open, onClose, onKeys }) {
  const { t } = useI18n();

  const [device, setDevice] = useState(guessDevice);
  const [downloads, setDownloads] = useState(null);
  const [storeOpen, setStoreOpen] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    api
      .downloads()
      .then((r) => alive && setDownloads(Array.isArray(r) ? r : []))
      .catch(() => alive && setDownloads([]));
    return () => {
      alive = false;
    };
  }, [open]);

  // Наш установщик под выбранное устройство: список отдаёт панель, там же
  // лежит последняя выложенная версия.
  const ourFile = useMemo(() => {
    const platform = OUR_BUILD[device];
    if (!platform) return null;
    return (downloads || []).find((one) => one.platform === platform) || null;
  }, [downloads, device]);

  const list = ORDER.map((id) => ({ id, ...APPS[id] })).filter((one) => one.on[device]);

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
          <span className="su-gear">{IC_DOWNLOAD}</span>
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
            onChange={setDevice}
          />
        </div>

        {list.map((one) => (
          <AppCard
            key={one.id}
            icon={IC_DOWNLOAD}
            title={one.name}
            text={t(`su.app${one.kind === "ours" ? "Ours" : one.kind === "vpn" ? "Vpn" : "Sub"}`)}
          >
            {one.kind === "ours" ? (
              downloads === null ? (
                <span className="su-wait">{t("su.waitFile")}</span>
              ) : ourFile?.url ? (
                <button
                  type="button"
                  className="ap-cta su-cta"
                  onClick={() => {
                    tmaHaptic("light");
                    tmaOpenLink(ourFile.url);
                  }}
                >
                  {t("su.download", { os: t(`su.dev.${device}`) })}
                </button>
              ) : (
                <span className="su-wait">{t("su.noFile")}</span>
              )
            ) : (
              <a
                className="ap-cta su-cta"
                href={one.store?.[device]}
                target="_blank"
                rel="noreferrer noopener"
              >
                {t("su.install", { app: one.name })}
              </a>
            )}
          </AppCard>
        ))}

        {/* В российском App Store этих приложений нет — подсказка о смене
            региона стоит там же, где их ставят. */}
        {device === "ios" && (
          <button
            type="button"
            className="su-more"
            onClick={() => {
              tmaHaptic("light");
              setStoreOpen(true);
            }}
          >
            {t("su.appStoreBtn")}
          </button>
        )}

        {/* Поставили программу — дальше нужен ключ, и он в своём разделе. */}
        <AppCard icon={IC_KEY} title={t("su.keysTitle")} text={t("su.keysLead")}>
          <button
            type="button"
            className="ap-cta su-cta su-cta-alt"
            onClick={() => {
              tmaHaptic("light");
              onKeys?.();
            }}
          >
            {t("su.toKeys")}
          </button>
        </AppCard>
      </div>
      <AppStoreSheet open={storeOpen} onClose={() => setStoreOpen(false)} />
    </ScreenShell>
  );
}
