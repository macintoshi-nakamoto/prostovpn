import { BrandLogo } from "./BrandLogo.jsx";
import { BRAND } from "../lib/brand.js";
import { Link } from "react-router-dom";
import { useT } from "../lib/i18n/index.jsx";
import {
  NEWS_TELEGRAM,
  SUPPORT_EMAIL,
  SUPPORT_MAILTO,
  SUPPORT_TELEGRAM,
  SUPPORT_TELEGRAM_NAME,
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
          <a href={SUPPORT_TELEGRAM} target="_blank" rel="noreferrer">
            {SUPPORT_TELEGRAM_NAME}
          </a>
          <a href={SUPPORT_MAILTO}>{SUPPORT_EMAIL}</a>
          <span>{t("footer.supportNote")}</span>
        </div>

        <div className="sf-bottom">
          <span>© {new Date().getFullYear()} {BRAND.name}</span>
          <div>
            <Link to="/terms">{t("footer.terms")}</Link>
            <Link to="/privacy">{t("footer.privacy")}</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
