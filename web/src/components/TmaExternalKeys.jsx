import { useEffect, useMemo, useState } from "react";
import { ScreenShell } from "./ScreenShell.jsx";
import { QrCode } from "./QrCode.jsx";
import { api } from "../lib/api";
import { isTma } from "../lib/telegram.js";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Ключ для стороннего приложения.
 *
 * Всё держится на одной ссылке-подписке: приложение само разбирает, какой
 * формат ему нужен, само перечитывает ключи и показывает остаток трафика.
 * Человеку остаётся выбрать программу и один раз вставить ссылку — или
 * нажать кнопку, которая откроет её прямо в приложении.
 */

/**
 * Приложения, которые понимают нашу подписку.
 *
 * `deep` — ссылка, по которой программа добавляет подписку сама. Формат у
 * каждой свой; где его нет, остаётся копирование, и это нормально.
 */
const APPS = [
  {
    id: "happ",
    name: "Happ",
    platforms: ["ios", "android", "mac", "win"],
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
    platforms: ["ios", "android", "mac", "win"],
    deep: (url) => `hiddify://import/${url}`,
    store: {
      ios: "https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532",
      android: "https://play.google.com/store/apps/details?id=app.hiddify.com",
      mac: "https://github.com/hiddify/hiddify-app/releases/latest",
      win: "https://github.com/hiddify/hiddify-app/releases/latest",
    },
  },
  {
    id: "v2rayng",
    name: "v2rayNG",
    platforms: ["android"],
    deep: (url) => `v2rayng://install-sub?url=${encodeURIComponent(url)}`,
    store: { android: "https://play.google.com/store/apps/details?id=com.v2ray.ang" },
  },
  {
    id: "streisand",
    name: "Streisand",
    platforms: ["ios", "mac"],
    deep: (url) => `streisand://import/${url}`,
    store: {
      ios: "https://apps.apple.com/app/streisand/id6450534064",
      mac: "https://apps.apple.com/app/streisand/id6450534064",
    },
  },
  {
    id: "nekobox",
    name: "NekoBox",
    platforms: ["android"],
    deep: null,
    store: { android: "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest" },
  },
];

const PLATFORMS = ["ios", "android", "mac", "win"];

function detectPlatform() {
  if (typeof navigator === "undefined") return "android";
  const ua = navigator.userAgent || "";
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  if (/Android/i.test(ua)) return "android";
  if (/Macintosh|Mac OS X/i.test(ua)) return "mac";
  if (/Windows/i.test(ua)) return "win";
  return "android";
}

export function TmaExternalKeys({ open, onClose }) {
  const { t } = useI18n();

  const [platform, setPlatform] = useState(detectPlatform);
  const [keys, setKeys] = useState(null);
  const [fresh, setFresh] = useState(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const load = () => {
    api
      .subscriptionKeys()
      .then((list) => setKeys(Array.isArray(list) ? list : []))
      .catch(() => setKeys([]));
  };

  useEffect(() => {
    if (open) load();
  }, [open]);

  const apps = useMemo(() => APPS.filter((app) => app.platforms.includes(platform)), [platform]);

  const issue = () => {
    setBusy(true);
    setError("");
    api
      .issueSubscriptionKey(label.trim())
      .then((created) => {
        setFresh(created);
        setLabel("");
        load();
      })
      .catch((problem) => setError(problem?.message || t("setup.ext.failed")))
      .finally(() => setBusy(false));
  };

  const revoke = (id) => {
    setBusy(true);
    api
      .revokeSubscriptionKey(id)
      .then(() => {
        if (fresh?.id === id) setFresh(null);
        load();
      })
      .catch(() => {})
      .finally(() => setBusy(false));
  };

  const copy = (value) => {
    navigator.clipboard?.writeText(value).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      },
      () => {},
    );
  };

  const url = fresh?.url || "";

  return (
    // Стрелка — только вне Telegram: внутри назад ведёт системная кнопка,
    // её показывает ScreenShell через pushBack. Та же запись, что у экрана
    // профиля в Account.jsx.
    <ScreenShell open={open} title={t("setup.ext.title")} back={!isTma()} onClose={onClose}>
      {/* Колонка с зазором, как .ap в кабинете. Без неё дети экрана стоят
          на голых полях, а у st-h нижний отступ отрицательный — он затягивал
          следующий блок ПОВЕРХ заголовка, и плашки закрашивали его собой. */}
      <div className="xk">
        <p className="xk-lead">{t("setup.ext.lead")}</p>

        <h3 className="st-h">{t("setup.ext.step1")}</h3>
        <div className="xk-tabs">
          {PLATFORMS.map((id) => (
            <button
              key={id}
              type="button"
              className={"xk-tab" + (platform === id ? " xk-tab-on" : "")}
              onClick={() => setPlatform(id)}
            >
              {t(`setup.ext.os.${id}`)}
            </button>
          ))}
        </div>

        <div className="ap-rows">
          {apps.map((app) => (
            <div className="ap-row xk-app" key={app.id}>
              <span className="ap-row-body">
                <span className="ap-row-t">{app.name}</span>
                <span className="ap-row-s">{t("setup.ext.appSub")}</span>
              </span>
              <a
                className="xk-get"
                href={app.store[platform]}
                target="_blank"
                rel="noreferrer noopener"
              >
                {t("setup.ext.install")}
              </a>
              {url && app.deep && (
                <a className="xk-add" href={app.deep(url)}>
                  {t("setup.ext.add")}
                </a>
              )}
            </div>
          ))}
        </div>

        <h3 className="st-h">{t("setup.ext.step2")}</h3>
        <p className="xk-note">{t("setup.ext.step2note")}</p>

        <div className="xk-issue">
          <input
            className="xk-input"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder={t("setup.ext.labelHint")}
            maxLength={64}
          />
          <button type="button" className="xk-btn" onClick={issue} disabled={busy}>
            {t("setup.ext.issue")}
          </button>
        </div>

        {error && <p className="xk-error">{error}</p>}

        {url && (
          <div className="xk-fresh">
            <span className="xk-fresh-t">{t("setup.ext.freshTitle")}</span>
            <span className="xk-fresh-w">{t("setup.ext.freshWarn")}</span>

            <button type="button" className="xk-url" onClick={() => copy(url)}>
              <code>{url}</code>
              <span className="xk-copy">{copied ? t("setup.ext.copied") : t("setup.ext.copy")}</span>
            </button>

            <div className="xk-qr">
              <QrCode value={url} size={190} />
            </div>
            <span className="xk-qr-note">{t("setup.ext.qrNote")}</span>
          </div>
        )}

        {Array.isArray(keys) && keys.length > 0 && (
          <>
            <h3 className="st-h">{t("setup.ext.listTitle")}</h3>
            <div className="ap-rows">
              {keys.map((key) => (
                <div className="ap-row xk-item" key={key.id}>
                  <span className="ap-row-body">
                    <span className="ap-row-t">{key.label || t("setup.ext.noLabel")}</span>
                    <span className="ap-row-s">
                      {key.last_used_at ? t("setup.ext.used") : t("setup.ext.neverUsed")}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="xk-revoke"
                    onClick={() => revoke(key.id)}
                    disabled={busy}
                  >
                    {t("setup.ext.revoke")}
                  </button>
                </div>
              ))}
            </div>
          </>
        )}

        <h3 className="st-h">{t("setup.ext.step3")}</h3>
        <ol className="xk-steps">
          <li>{t("setup.ext.s1")}</li>
          <li>{t("setup.ext.s2")}</li>
          <li>{t("setup.ext.s3")}</li>
        </ol>
        <p className="xk-note">{t("setup.ext.tail")}</p>
      </div>
    </ScreenShell>
  );
}
