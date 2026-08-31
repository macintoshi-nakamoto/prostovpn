import { useEffect, useMemo, useState } from "react";
import { QrCode } from "./QrCode.jsx";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n/index.jsx";

/**
 * Установка в стороннее приложение.
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
 * каждой свой; там, где его нет, остаётся копирование, и это нормально.
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
    store: {
      android: "https://play.google.com/store/apps/details?id=com.v2ray.ang",
    },
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
    store: {
      android: "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest",
    },
  },
];

function detectPlatform() {
  if (typeof navigator === "undefined") return "android";
  const ua = navigator.userAgent || "";
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  if (/Android/i.test(ua)) return "android";
  if (/Macintosh|Mac OS X/i.test(ua)) return "mac";
  if (/Windows/i.test(ua)) return "win";
  return "android";
}

export function SetupExternal({ onSwitch }) {
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

  useEffect(load, []);

  const apps = useMemo(
    () => APPS.filter((app) => app.platforms.includes(platform)),
    [platform],
  );

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
    <div className="sx">
      <header className="sx-head">
        <div>
          <h2 className="sx-title">{t("setup.ext.title")}</h2>
          <p className="sx-lead">{t("setup.ext.lead")}</p>
        </div>
        <button type="button" className="sx-switch" onClick={onSwitch}>
          {t("setup.ext.switch")}
        </button>
      </header>

      <section className="sx-step">
        <h3 className="sx-step-title">
          <span className="sx-num">1</span>
          {t("setup.ext.step1")}
        </h3>

        <div className="sx-tabs">
          {["ios", "android", "mac", "win"].map((id) => (
            <button
              key={id}
              type="button"
              className={"sx-tab" + (platform === id ? " sx-tab-on" : "")}
              onClick={() => setPlatform(id)}
            >
              {t(`setup.ext.os.${id}`)}
            </button>
          ))}
        </div>

        <div className="sx-apps">
          {apps.map((app) => (
            <article key={app.id} className="sx-app">
              <span className="sx-app-name">{app.name}</span>
              <a
                className="sx-app-get"
                href={app.store[platform]}
                target="_blank"
                rel="noreferrer noopener"
              >
                {t("setup.ext.install")}
              </a>
              {url && app.deep && (
                <a className="sx-app-add" href={app.deep(url)}>
                  {t("setup.ext.add")}
                </a>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="sx-step">
        <h3 className="sx-step-title">
          <span className="sx-num">2</span>
          {t("setup.ext.step2")}
        </h3>
        <p className="sx-note">{t("setup.ext.step2note")}</p>

        <div className="sx-issue">
          <input
            className="sx-input"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder={t("setup.ext.labelHint")}
            maxLength={64}
          />
          <button type="button" className="sx-issue-btn" onClick={issue} disabled={busy}>
            {t("setup.ext.issue")}
          </button>
        </div>

        {error && <p className="sx-error">{error}</p>}

        {url && (
          <div className="sx-fresh">
            <p className="sx-fresh-title">{t("setup.ext.freshTitle")}</p>
            <p className="sx-fresh-warn">{t("setup.ext.freshWarn")}</p>

            <div className="sx-url">
              <code className="sx-url-text">{url}</code>
              <button type="button" className="sx-copy" onClick={() => copy(url)}>
                {copied ? t("setup.ext.copied") : t("setup.ext.copy")}
              </button>
            </div>

            <div className="sx-qr">
              <QrCode value={url} size={190} />
              <p className="sx-qr-note">{t("setup.ext.qrNote")}</p>
            </div>
          </div>
        )}

        {Array.isArray(keys) && keys.length > 0 && (
          <div className="sx-list">
            <p className="sx-list-title">{t("setup.ext.listTitle")}</p>
            {keys.map((key) => (
              <div key={key.id} className="sx-item">
                <span className="sx-item-name">{key.label || t("setup.ext.noLabel")}</span>
                <span className="sx-item-used">
                  {key.last_used_at ? t("setup.ext.used") : t("setup.ext.neverUsed")}
                </span>
                <button
                  type="button"
                  className="sx-revoke"
                  onClick={() => revoke(key.id)}
                  disabled={busy}
                >
                  {t("setup.ext.revoke")}
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="sx-step">
        <h3 className="sx-step-title">
          <span className="sx-num">3</span>
          {t("setup.ext.step3")}
        </h3>
        <ol className="sx-steps">
          <li>{t("setup.ext.s1")}</li>
          <li>{t("setup.ext.s2")}</li>
          <li>{t("setup.ext.s3")}</li>
        </ol>
        <p className="sx-note">{t("setup.ext.tail")}</p>
      </section>
    </div>
  );
}
