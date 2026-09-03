import { Link, useLocation } from "react-router-dom";
import { Controls } from "./Controls.jsx";
import { useSession } from "../lib/session.jsx";
import { useScrolled } from "../lib/hooks";
import { useT } from "../lib/i18n/index.jsx";
import { BrandLogo } from "./BrandLogo.jsx";
import { BRAND } from "../lib/brand.js";
import "./site-header.css";

export function SiteHeader() {
  const scrolled = useScrolled(60);
  const { authed } = useSession();
  const { pathname } = useLocation();
  const t = useT();
  const onLanding = pathname === "/";
  const onLogin = pathname === "/login";

  const toTop = (e) => {
    if (!onLanding) return;
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const section = (id) => (onLanding ? `#${id}` : `/#${id}`);

  return (
    <header className={`sh${scrolled ? " sh-solid" : ""}`}>
      <div className="wrap sh-in">
        <Link to="/" className="sh-logo" onClick={toTop}>
          <BrandLogo />
        </Link>
        {/* Разделы лендинга есть только у бренда с лендингом. */}
        {BRAND.landing && (
        <nav className="sh-nav">
          <a href={section("speed")}>{t("nav.speed")}</a>
          <a href={section("app")}>{t("nav.app")}</a>
          <a href={section("plans")}>{t("nav.plans")}</a>
          <a href={section("security")}>{t("nav.security")}</a>
          <Link to="/guide">{t("nav.guide")}</Link>
          <Link to="/faq">{t("nav.faq")}</Link>
        </nav>
        )}
        <div className="sh-right">
          <Controls />
          {!onLogin && (
            <Link to={authed ? "/account" : "/login"} className="sh-cta">
              {authed ? t("nav.account") : t("nav.signin")}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
