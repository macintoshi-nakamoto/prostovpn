import { BRAND } from "../lib/brand.js";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Picture } from "./Picture.jsx";
import { Reveal } from "./Reveal.jsx";
import { GuideTip } from "./GuideTip.jsx";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n/index.jsx";
import { SUPPORT_CHAT, SUPPORT_EMAIL, SUPPORT_MAILTO, SUPPORT_TELEGRAM } from "../lib/contacts.js";
import "../pages/guide.css";

const PLATFORMS = ["android", "ios", "mac", "win", "tv"];

const DOWNLOAD_PLATFORM = { android: "android", tv: "android", mac: "macos", win: "windows" };

const APP_STORE_AMNEZIA = "https://apps.apple.com/app/amneziavpn/id1600529900";

const NEEDS_KEY = new Set(["ios"]);

export function GuideBody({ login, embedded = false }) {
  const { t, raw } = useI18n();
  const [os, setOs] = useState("android");
  const [downloads, setDownloads] = useState({});

  const [storeOpen, setStoreOpen] = useState(false);

  useEffect(() => {
    api
      .downloads()
      .then((list) => {
        if (!Array.isArray(list)) return;
        const map = {};
        for (const item of list) map[item.platform] = item.url;
        setDownloads(map);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const ua = navigator.userAgent || "";
    if (/iPhone|iPad|iPod/i.test(ua)) setOs("ios");
    else if (/Android/i.test(ua)) setOs("android");
    else if (/Macintosh|Mac OS X/i.test(ua)) setOs("mac");
    else if (/Windows/i.test(ua)) setOs("win");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.location.hash !== "#appstore") return;

    setOs("ios");
    setStoreOpen(true);
    const timer = setTimeout(() => {
      document.getElementById("appstore")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 120);
    return () => clearTimeout(timer);
  }, []);

  const current = useMemo(() => raw(`guide.os.${os}`) || {}, [os, raw]);
  const steps = current.steps || [];
  const shots = current.shots || [];
  const needsKey = NEEDS_KEY.has(os);

  const downloadHref = needsKey ? APP_STORE_AMNEZIA : downloads[DOWNLOAD_PLATFORM[os]];
  const splitShots = raw("guide.split.shots") || [];
  const splitSteps = raw("guide.split.steps") || [];
  const helpCards = raw("guide.help.cards") || [];
  const features = raw("guide.features") || null;

  return (
    <div className={embedded ? "gd-embedded" : undefined}>
      <section className="gd-tabs-row">
        <div className="wrap gd-tabs" role="tablist" aria-label={t("guide.breadcrumbCurrent")}>
          {PLATFORMS.map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={os === id}
              className={`gd-tab${os === id ? " gd-tab-on" : ""}`}
              onClick={() => setOs(id)}
            >
              {t(`guide.platforms.${id}`)}
            </button>
          ))}
        </div>
      </section>

      <section className="gd-body">
        <div className="wrap gd-body-in">
          <div className="gd-main">
            <h2 className="gd-os-title">{current.title}</h2>

            <div className="gd-app">
              {needsKey ? (
                <img className="gd-app-icon" src="/assets/guide/amnezia-icon.svg" alt="AmneziaVPN" />
              ) : (
                <Picture className="gd-app-icon" src="/assets/guide/app-icon.png" alt={BRAND.name} />
              )}
              <div className="gd-app-text">
                <span className="gd-app-title">{current.appTitle}</span>
                <span className="gd-app-sub">{current.appText}</span>
              </div>
              {downloadHref ? (
                <a
                  className="btn btn-primary gd-app-btn"
                  href={downloadHref}
                  target={needsKey ? "_blank" : undefined}
                  rel={needsKey ? "noreferrer" : undefined}
                  download={needsKey ? undefined : true}
                >
                  {current.download || t("guide.downloadFallback")}
                </a>
              ) : (
                <span className="gd-soon">{t("guide.soon")}</span>
              )}
            </div>

            <ol className="gd-steps">
              {steps.map(([title, text], index) => (
                <li className="gd-step" key={title}>
                  <span className="gd-step-n">{index + 1}</span>
                  <span className="gd-step-text">
                    <span className="gd-step-title">{title}</span>
                    <span className="gd-step-sub">{text}</span>
                  </span>
                </li>
              ))}
            </ol>

            {shots.length > 0 && (
              <div className="gd-shots">
                <span className="gd-shots-title">{t("guide.shotsTitle")}</span>
                <div className="gd-shots-grid">
                  {shots.map((caption, index) => (
                    <figure key={caption}>
                      <Picture src={`/assets/guide/guide-ios-${index + 1}.jpg`} alt={caption} />
                      <figcaption>{caption}</figcaption>
                    </figure>
                  ))}
                </div>
              </div>
            )}

            {needsKey && (
              <section className="gd-store" id="appstore">
                <button
                  type="button"
                  className="gd-store-head"
                  aria-expanded={storeOpen}
                  onClick={() => setStoreOpen((on) => !on)}
                >
                  <span className="gd-store-head-text">
                    <span className="gd-store-title">{t("guide.appstore.title")}</span>
                    <span className="gd-store-lead">{t("guide.appstore.lead")}</span>
                  </span>
                  <span className={`gd-store-chev${storeOpen ? " gd-store-chev-on" : ""}`} aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                </button>

                {storeOpen && (
                  <div className="gd-store-body">
                    {(raw("guide.appstore.ways") || []).map((way, wi) => (
                      <div className="gd-store-way" key={way.title}>
                        <span className="gd-store-way-title">{way.title}</span>
                        <span className="gd-store-way-note">{way.note}</span>
                        <ol className="gd-store-steps">
                          {(way.steps || []).map((step, si) => (
                            <li key={step}>
                              <span className="gd-store-n">{wi === 0 ? si + 1 : si + 1}</span>
                              <span>{step}</span>
                            </li>
                          ))}
                        </ol>
                      </div>
                    ))}

                    <div className="gd-store-shots">
                      {(raw("guide.appstore.shots") || []).map((caption, index) => (
                        <figure key={caption}>
                          <Picture
                            src={`/assets/guide/guide-store-${index + 1}.jpg`}
                            alt={caption}
                            loading="lazy"
                            decoding="async"
                          />
                          <figcaption>{caption}</figcaption>
                        </figure>
                      ))}
                    </div>

                    <div className="gd-store-warn">
                      <span className="gd-store-warn-title">{t("guide.appstore.warnTitle")}</span>
                      <ul>
                        {(raw("guide.appstore.warns") || []).map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}
              </section>
            )}

            {!embedded && (
              <div className="gd-done">
                <span>{t("guide.done")}</span>
                <Link to="/account" className="btn btn-primary">
                  {t("guide.toAccount")}
                </Link>
              </div>
            )}
          </div>

          <aside className="gd-aside">
            <div className="gd-aside-card gd-aside-dark">
              <span className="gd-aside-title">
                {needsKey ? t("guide.asideKeyTitle") : t("guide.asideLoginTitle")}
              </span>
              <span className="gd-aside-text">
                {needsKey ? t("guide.asideKeyText") : t("guide.asideLoginText")}
              </span>
              {embedded ? (
                login && (
                  <span className="gd-aside-login">
                    {t("setup.noteLabel")}: <b>{login}</b>
                  </span>
                )
              ) : (
                <Link to="/account" className="btn btn-primary gd-aside-btn">
                  {t("guide.toAccount")}
                </Link>
              )}
              <a
                className="btn gd-aside-ghost"
                href={SUPPORT_TELEGRAM}
                target="_blank"
                rel="noreferrer"
              >
                {t("guide.asideBot")}
              </a>
            </div>

            {!embedded && (
              <div className="gd-aside-card">
                <span className="gd-aside-title">{t("guide.asideNeedTitle")}</span>
                <span className="gd-aside-text gd-aside-text-dim">{t("guide.asideNeedText")}</span>
                <Link to="/login" className="gd-aside-link">
                  {t("guide.asideCreate")}
                </Link>
              </div>
            )}
          </aside>
        </div>
      </section>

      {features && (
        <section className="gd-feat" id="features">
          <div className="wrap gd-feat-in">
            <div className="gd-feat-head">
              <span className="gd-eyebrow">{features.eyebrow}</span>
              <h2>{features.title}</h2>
              <p>{features.lead}</p>
            </div>
            <div className="gd-feat-grid">
              {(features.cards || []).map(([title, text], index) => (
                <Reveal className="gd-feat-card" key={title} delay={index * 50}>
                  <span className="gd-feat-n">{String(index + 1).padStart(2, "0")}</span>
                  <span className="gd-feat-title">{title}</span>
                  <span className="gd-feat-text">{text}</span>
                </Reveal>
              ))}
            </div>
          </div>
        </section>
      )}

      <section className="gd-split" id="split">
        <div className="wrap gd-split-in">
          <div className="gd-split-top">
            <div className="gd-split-text">
              <span className="gd-eyebrow">{t("guide.split.eyebrow")}</span>
              <h2>{t("guide.split.title")}</h2>
              <p>{t("guide.split.lead1")}</p>
              <p>{t("guide.split.lead2")}</p>
              <div className="gd-split-actions">
                <Link to={embedded ? "/account" : "/account"} className="btn btn-primary">
                  {t("guide.split.fileButton")}
                </Link>
                <a
                  className="btn gd-ghost"
                  href={SUPPORT_TELEGRAM}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("guide.split.botButton")}
                </a>
              </div>
            </div>

            <ol className="gd-split-steps">
              {splitSteps.map(([title, text], index) => (
                <li key={title}>
                  <span className="gd-split-n">{index + 1}</span>
                  <span>
                    <span className="gd-split-step-title">{title}</span>
                    <span className="gd-split-step-sub">{text}</span>
                  </span>
                </li>
              ))}
            </ol>
          </div>

          <div className="gd-split-shots">
            {splitShots.map((caption, index) => (
              <figure key={caption}>
                <Picture src={`/assets/guide/guide-split-${index + 1}.jpg`} alt={caption} />
                <figcaption>{caption}</figcaption>
              </figure>
            ))}
          </div>
        </div>
      </section>

      <section className="gd-help" id="help">
        <div className="wrap gd-help-in">
          <div className="gd-help-head">
            <h2>{t("guide.help.title")}</h2>
            <p>{t("guide.help.lead")}</p>
          </div>

          <div className="gd-help-cards">
            {helpCards.map(([title, text]) => (
              <div className="gd-help-card" key={title}>
                <span className="gd-help-card-title">{title}</span>
                <span className="gd-help-card-text">{text}</span>
              </div>
            ))}
          </div>

          <div className="gd-ask">
            <div className="gd-ask-text">
              <span className="gd-ask-title">{t("guide.help.askTitle")}</span>
              <span className="gd-ask-sub">{t("guide.help.askText")}</span>
            </div>
            <div className="gd-ask-actions">
              <a className="btn btn-primary" href={SUPPORT_CHAT} target="_blank" rel="noreferrer">
                {t("guide.help.askBot")}
              </a>
              <Link to="/faq" className="btn btn-dark">
                {t("guide.help.askFaq")}
              </Link>
              <a className="btn btn-dark" href={SUPPORT_MAILTO}>
                {SUPPORT_EMAIL}
              </a>
            </div>
          </div>
        </div>
      </section>

      {needsKey && !embedded && (
        <GuideTip
          onOpen={() => {
            setStoreOpen(true);

            setTimeout(() => {
              document.getElementById("appstore")?.scrollIntoView({ behavior: "smooth", block: "start" });
            }, 60);
          }}
        />
      )}
    </div>
  );
}
