import { useEffect, useState } from "react";
import { BrandLogo } from "./BrandLogo.jsx";
import { api } from "../lib/api";
import { BRAND } from "../lib/brand.js";
import { Link } from "react-router-dom";
import { useT } from "../lib/i18n/index.jsx";
import {
  NEWS_TELEGRAM,
  SUPPORT_EMAIL,
  SUPPORT_MAILTO,
  SUPPORT_CHAT,
  SUPPORT_CHAT_NAME,
  SUPPORT_TELEGRAM,
} from "../lib/contacts.js";
import "./site-footer.css";

export function SiteFooter() {
  const t = useT();

  return (
    <footer className="sf">
      <div className="wrap sf-in">
        <BrandLogo className="sf-logo" />

        <div className="sf-cols">
          <div>
            <a href="#plans">{t("footer.plans")}</a>
            <a href="#app">{t("footer.app")}</a>
            <a href="#speed">{t("footer.servers")}</a>
            <a href="#security">{t("footer.security")}</a>
          </div>
          <div>
            <Link to="/guide">{t("footer.guide")}</Link>
            <Link to="/status">{t("footer.status")}</Link>
            <Link to="/faq">{t("footer.faq")}</Link>
            <Link to="/contacts">{t("footer.support")}</Link>
            <a href={SUPPORT_TELEGRAM} target="_blank" rel="noreferrer">
              {t("footer.bot")}
            </a>
            <a href={NEWS_TELEGRAM} target="_blank" rel="noreferrer">
              {t("footer.channel")}
            </a>
          </div>
          <div>
            <Link to="/terms">{t("footer.terms")}</Link>
            <Link to="/privacy">{t("footer.privacy")}</Link>
            <Link to="/aup">{t("footer.aup")}</Link>
            <Link to="/refund">{t("footer.refund")}</Link>
            <Link to="/licenses">{t("footer.licenses")}</Link>
            <Link to="/contacts">{t("footer.contacts")}</Link>
            <a href={SUPPORT_MAILTO}>{t("footer.email")}</a>
          </div>
        </div>

        <div className="sf-contact">
          <a href={SUPPORT_CHAT} target="_blank" rel="noreferrer">
            {SUPPORT_CHAT_NAME}
          </a>
          <a href={SUPPORT_MAILTO}>{SUPPORT_EMAIL}</a>
          <span>{t("footer.supportNote")}</span>
        </div>

        <FooterStatus t={t} />

        <div className="sf-bottom">
          <span>
            © {new Date().getFullYear()} {BRAND.name} · {t("landing.hero.eyebrow")}
          </span>
          <div>
            <Link to="/terms">{t("footer.terms")}</Link>
            <Link to="/privacy">{t("footer.privacy")}</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}

/**
 * Состояние серверов одной строкой. Спрашиваем один раз при появлении
 * подвала: сюда доскролливают редко, а держать опрос на каждой странице
 * ни к чему. Точка зелёная — всё работает, красная — что-то легло и
 * написано, что именно.
 */
function FooterStatus({ t }) {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let alive = true;
    api
      .status()
      .then((r) => alive && setStatus(r))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  if (status && !status.total) return null;
  const bad = Boolean(status && status.down > 0);
  let text = t("footer.liveWait");
  if (status && bad) {
    text =
      status.down === 1
        ? t("footer.liveOne", {
            country: (status.servers.find((one) => !one.up) || {}).country || "",
          })
        : t("footer.liveDown", { n: status.down });
  } else if (status) text = t("footer.liveUp");

  return (
    <Link to="/status" className={"sf-live" + (bad ? " is-bad" : "") + (status ? "" : " is-wait")}>
      <i className="sf-live-dot" aria-hidden="true" />
      <span className="sf-live-title">{t("footer.liveTitle")}</span>
      <span className="sf-live-text">{text}</span>
      <span className="sf-live-more">{t("footer.liveCheck")} →</span>
    </Link>
  );
}
