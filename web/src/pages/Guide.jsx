import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Picture } from "../components/Picture.jsx";
import { Reveal } from "../components/Reveal.jsx";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n/index.jsx";
import { SUPPORT_EMAIL, SUPPORT_MAILTO, SUPPORT_TELEGRAM } from "../lib/contacts.js";
import "./guide.css";

/*
 * Инструкция по подключению.
 *
 * Одна страница на пять платформ, а не пять страниц: шаги отличаются тремя
 * строками из пяти, и разводить их по адресам значит четырежды повторить
 * общее — и однажды поправить только в одном месте.
 *
 * Ссылки на установщики берутся живыми из панели (/api/v1/downloads): версия
 * там меняется каждую выкладку, и зашитый в вёрстку файл устарел бы к первому
 * же релизу. Не ответила панель — кнопки просто нет, а шаги остаются: они
 * полезны и без неё.
 */

/** Порядок вкладок. Android первым: с него приходит большинство. */
const PLATFORMS = ["android", "ios", "mac", "win", "tv"];

/** Какой файл из панели показывать на вкладке. TV ставится тем же APK. */
const DOWNLOAD_PLATFORM = { android: "android", tv: "android", mac: "macos", win: "windows" };

/** У iPhone своего приложения нет — там AmneziaVPN и ключ подключения. */
const APP_STORE_AMNEZIA = "https://apps.apple.com/app/amneziavpn/id1600529900";

/** Что определяет вид боковой колонки: ключ или логин с паролем. */
const NEEDS_KEY = new Set(["ios"]);

export function Guide() {
  const { t, raw } = useI18n();
  const [os, setOs] = useState("android");
  const [downloads, setDownloads] = useState({});

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

  /*
   * Первая вкладка — под систему, с которой пришли. Человек, открывший
   * инструкцию с макбука, не должен первым делом искать свою платформу среди
   * пяти кнопок.
   */
  useEffect(() => {
    const ua = navigator.userAgent || "";
    if (/iPhone|iPad|iPod/i.test(ua)) setOs("ios");
    else if (/Android/i.test(ua)) setOs("android");
    else if (/Macintosh|Mac OS X/i.test(ua)) setOs("mac");
    else if (/Windows/i.test(ua)) setOs("win");
  }, []);

  const current = useMemo(() => raw(`guide.os.${os}`) || {}, [os, raw]);
  const steps = current.steps || [];
  const shots = current.shots || [];
  const needsKey = NEEDS_KEY.has(os);

  const downloadHref = needsKey ? APP_STORE_AMNEZIA : downloads[DOWNLOAD_PLATFORM[os]];
  const splitShots = raw("guide.split.shots") || [];
  const splitSteps = raw("guide.split.steps") || [];
  const helpCards = raw("guide.help.cards") || [];

  return (
    <div className="gd">
      <SiteHeader />

      <section className="gd-hero" id="top">
        <div className="wrap">
          <Reveal className="gd-hero-in">
            <div className="gd-crumbs">
              <Link to="/">{t("guide.breadcrumbHome")}</Link>
              <span>/</span>
              <span className="gd-crumb-current">{t("guide.breadcrumbCurrent")}</span>
            </div>
            <h1>{t("guide.title")}</h1>
            <p>{t("guide.lead")}</p>
            <div className="gd-meta">
              <span>{t("guide.updated")}</span>
              <span>{t("guide.reading")}</span>
            </div>
          </Reveal>
        </div>
      </section>

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
                <Picture className="gd-app-icon" src="/assets/guide/app-icon.png" alt="Prosto VPN" />
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

            <div className="gd-done">
              <span>{t("guide.done")}</span>
              <Link to="/account" className="btn btn-primary">
                {t("guide.toAccount")}
              </Link>
            </div>
          </div>

          <aside className="gd-aside">
            <div className="gd-aside-card gd-aside-dark">
              <span className="gd-aside-title">
                {needsKey ? t("guide.asideKeyTitle") : t("guide.asideLoginTitle")}
              </span>
              <span className="gd-aside-text">
                {needsKey ? t("guide.asideKeyText") : t("guide.asideLoginText")}
              </span>
              <Link to="/account" className="btn btn-primary gd-aside-btn">
                {t("guide.toAccount")}
              </Link>
              <a
                className="btn gd-aside-ghost"
                href={SUPPORT_TELEGRAM}
                target="_blank"
                rel="noreferrer"
              >
                {t("guide.asideBot")}
              </a>
            </div>

            <div className="gd-aside-card">
              <span className="gd-aside-title">{t("guide.asideNeedTitle")}</span>
              <span className="gd-aside-text gd-aside-text-dim">{t("guide.asideNeedText")}</span>
              <Link to="/login" className="gd-aside-link">
                {t("guide.asideCreate")}
              </Link>
            </div>
          </aside>
        </div>
      </section>

      <section className="gd-split" id="split">
        <div className="wrap gd-split-in">
          <div className="gd-split-top">
            <div className="gd-split-text">
              <span className="gd-eyebrow">{t("guide.split.eyebrow")}</span>
              <h2>{t("guide.split.title")}</h2>
              <p>{t("guide.split.lead1")}</p>
              <p>{t("guide.split.lead2")}</p>
              <div className="gd-split-actions">
                <Link to="/account" className="btn btn-primary">
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
              <a className="btn btn-primary" href={SUPPORT_TELEGRAM} target="_blank" rel="noreferrer">
                {t("guide.help.askBot")}
              </a>
              <a className="btn btn-dark" href={SUPPORT_MAILTO}>
                {SUPPORT_EMAIL}
              </a>
            </div>
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
