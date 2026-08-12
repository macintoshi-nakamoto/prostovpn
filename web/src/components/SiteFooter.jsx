import { Link } from "react-router-dom";
import { Picture } from "./Picture.jsx";
import { useT } from "../lib/i18n/index.jsx";
import "./site-footer.css";

/** Подвал лендинга: навигация, контакт поддержки, копирайт. Из макета. */
export function SiteFooter() {
  const t = useT();

  return (
    <footer className="sf">
      <div className="wrap sf-in">
        <Picture className="sf-logo" src="/assets/logo.png" alt="PROSTO" />

        <div className="sf-cols">
          <div>
            <a href="#plans">{t("footer.plans")}</a>
            <a href="#app">{t("footer.app")}</a>
            <a href="#speed">{t("footer.servers")}</a>
            <a href="#security">{t("footer.security")}</a>
          </div>
          <div>
            <Link to="/faq">{t("footer.faq")}</Link>
            <Link to="/contacts">{t("footer.support")}</Link>
            {/* Канал, а не поддержка: за помощью ведёт соседняя ссылка. */}
            <a href="https://t.me/prostovpn_tg" target="_blank" rel="noreferrer">
              {t("footer.channel")}
            </a>
            <a href="https://t.me/prostovpnn_bot" target="_blank" rel="noreferrer">
              {t("footer.bot")}
            </a>
          </div>
          <div>
            <Link to="/terms">{t("footer.terms")}</Link>
            <Link to="/privacy">{t("footer.privacy")}</Link>
            <Link to="/contacts">{t("footer.contacts")}</Link>
          </div>
          <div className="sf-stores">
            <Link to="/login" className="btn btn-dark sf-store">
              <Picture src="/assets/ic-appstore.png" />
              App Store
            </Link>
            <Link to="/login" className="btn btn-dark sf-store">
              <Picture src="/assets/ic-googleplay.png" />
              Google Play
            </Link>
          </div>
        </div>

        <div className="sf-contact">
          <a href="https://t.me/prosto_vpn_supp" target="_blank" rel="noreferrer">
            @prosto_vpn_supp
          </a>
          <span>{t("footer.supportNote")}</span>
        </div>

        <div className="sf-bottom">
          <span>© {new Date().getFullYear()} Prosto VPN</span>
          <div>
            <Link to="/terms">{t("footer.terms")}</Link>
            <Link to="/privacy">{t("footer.privacy")}</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
