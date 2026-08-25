import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { Reveal } from "../components/Reveal.jsx";
import { GuideBody } from "../components/GuideBody.jsx";
import { useI18n } from "../lib/i18n/index.jsx";
import "./guide.css";

export function Guide() {
  const { t } = useI18n();

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

      <GuideBody />

      <SiteFooter />
    </div>
  );
}
